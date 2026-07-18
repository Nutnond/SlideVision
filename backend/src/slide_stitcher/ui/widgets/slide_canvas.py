from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from slide_stitcher.models import SlideMetadata, SlidePosition
from slide_stitcher.ui.widgets.slide_item import SlideItem

DEFAULT_DISPLAY_MAX = 400.0
MIN_ZOOM = 0.05
MAX_ZOOM = 10.0


def _checker_brush() -> QBrush:
    tile = QPixmap(24, 24)
    tile.fill(QColor("#0b1224"))
    painter = QPainter(tile)
    painter.fillRect(0, 0, 12, 12, QColor("#1e293b"))
    painter.fillRect(12, 12, 12, 12, QColor("#1e293b"))
    painter.end()
    return QBrush(tile)


class SlideCanvasScene(QGraphicsScene):
    pass


class SlideCanvas(QGraphicsView):
    slideMoved = Signal(str, float, float)
    slideResized = Signal(str, float, float, float, float)
    slideRotated = Signal(str, float)
    slideCropped = Signal(str)
    selectionChanged = Signal(object)  # list[str] of selected slide_ids

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setBackgroundBrush(_checker_brush())
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.StrongFocus)

        self.scene = SlideCanvasScene()
        self.scene.setSceneRect(-5000, -5000, 10000, 10000)
        self.setScene(self.scene)
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)

        self._items_by_id: dict[str, SlideItem] = {}
        self._zoom = 1.0
        self._panning = False
        self._pan_last_pos = None

        # Mac trackpad gestures
        self.viewport().grabGesture(Qt.PinchGesture)
        self.viewport().grabGesture(Qt.SwipeGesture)

    def _on_scene_selection_changed(self) -> None:
        ids = [sid for sid, item in self._items_by_id.items() if item.isSelected()]
        self.selectionChanged.emit(ids)

    def add_slide(self, slide: SlideMetadata, pixmap: QPixmap) -> SlideItem:
        if slide.id in self._items_by_id:
            existing = self._items_by_id[slide.id]
            self.scene.clearSelection()
            existing.setSelected(True)
            self.ensureVisible(existing)
            return existing

        scale = min(
            DEFAULT_DISPLAY_MAX / max(1, pixmap.width()),
            DEFAULT_DISPLAY_MAX / max(1, pixmap.height()),
            1.0,
        )
        display_w = float(pixmap.width()) * scale
        display_h = float(pixmap.height()) * scale

        item = SlideItem(slide.id, pixmap)
        item.moved.connect(self.slideMoved)
        item.resized.connect(self.slideResized)
        item.rotated.connect(self.slideRotated)
        item.cropped.connect(self.slideCropped)
        item.setZValue(len(self._items_by_id) + 1)

        center = self.mapToScene(self.viewport().rect().center())
        item.set_geometry(
            center.x() - display_w / 2,
            center.y() - display_h / 2,
            display_w,
            display_h,
        )

        self.scene.addItem(item)
        self._items_by_id[slide.id] = item

        self.scene.clearSelection()
        item.setSelected(True)
        self.ensureVisible(item)
        return item

    def has_slide(self, slide_id: str) -> bool:
        return slide_id in self._items_by_id

    def remove_slide(self, slide_id: str) -> None:
        item = self._items_by_id.pop(slide_id, None)
        if item is not None:
            self.scene.removeItem(item)

    def clear_slides(self) -> None:
        for item in list(self._items_by_id.values()):
            self.scene.removeItem(item)
        self._items_by_id.clear()

    def load_positions(self, positions: list[SlidePosition]) -> None:
        for pos in positions:
            item = self._items_by_id.get(pos.id)
            if item is not None:
                item.set_geometry(pos.x, pos.y, pos.w, pos.h)
                item.set_rotation(pos.rotation)
                item.set_crop(pos.crop_x, pos.crop_y, pos.crop_w, pos.crop_h)
                item.set_applied_crop(pos.applied_x, pos.applied_y, pos.applied_w, pos.applied_h)

    def get_positions(self) -> list[SlidePosition]:
        out: list[SlidePosition] = []
        for sid, item in self._items_by_id.items():
            x, y, w, h = item.current_geometry()
            cx, cy, cw, ch = item.get_crop()
            ax, ay, aw, ah = item.get_applied_crop()
            out.append(
                SlidePosition(
                    id=sid,
                    x=x,
                    y=y,
                    w=w,
                    h=h,
                    rotation=item._rotation,
                    crop_x=cx,
                    crop_y=cy,
                    crop_w=cw,
                    crop_h=ch,
                    applied_x=ax,
                    applied_y=ay,
                    applied_w=aw,
                    applied_h=ah,
                )
            )
        return out

    def get_selected_item(self) -> SlideItem | None:
        for sid, item in self._items_by_id.items():
            if item.isSelected():
                return item
        return None

    def apply_crop_selected(self) -> tuple[str, tuple[float, float, float, float]] | None:
        """Commit the current crop on the selected slide. Returns (slide_id, applied_delta) or None."""
        item = self.get_selected_item()
        if item is None:
            return None
        if not item.apply_crop():
            return None
        delta = item.pop_last_applied_delta()
        if delta is None:
            return None
        return item.slide_id, delta

    def get_selected_ids(self) -> list[str]:
        return [sid for sid, item in self._items_by_id.items() if item.isSelected()]

    def remove_selected(self) -> list[str]:
        ids = self.get_selected_ids()
        for sid in ids:
            self.remove_slide(sid)
        return ids

    def wheelEvent(self, event) -> None:
        # Plain wheel/trackpad scroll = pan (let QAbstractScrollArea handle scrollbars).
        # Cmd+wheel = zoom (mouse users without trackpad).
        # Pinch (trackpad) is handled separately via gestureEvent.
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            new_zoom = self._zoom * factor
            new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, new_zoom))
            if new_zoom != self._zoom:
                ratio = new_zoom / self._zoom
                self.scale(ratio, ratio)
                self._zoom = new_zoom
            event.accept()
            return
        super().wheelEvent(event)

    def event(self, event):
        if event.type() == QEvent.Gesture:
            self._handle_gesture(event)
            return True
        return super().event(event)

    def _handle_gesture(self, event) -> None:
        for gesture in event.gestures():
            if gesture.gestureType() == Qt.PinchGesture:
                self._handle_pinch(gesture)

    def _handle_pinch(self, pinch) -> None:
        # pinch.scaleFactor() is incremental per gesture update
        sf = pinch.scaleFactor()
        if abs(sf - 1.0) < 1e-3:
            return
        # Center on the gesture's centerPoint (screen coords) → map to scene
        center_viewport = self.mapFromGlobal(pinch.centerPoint().toPoint())
        center_scene = self.mapToScene(center_viewport)

        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom * sf))
        ratio = new_zoom / self._zoom
        self.scale(ratio, ratio)
        self._zoom = new_zoom

        # Re-anchor on the cursor
        new_center_viewport = self.mapFromScene(center_scene)
        delta = new_center_viewport - center_viewport
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta.y())

    def mousePressEvent(self, event) -> None:
        if event.button() in (Qt.MiddleButton, Qt.LeftButton):
            item_at = self.itemAt(event.position().toPoint() if hasattr(event, "position") else event.pos())
            if item_at is None:
                self._panning = True
                self._pan_last_pos = event.position() if hasattr(event, "position") else event.pos()
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning and self._pan_last_pos is not None:
            cur = event.position() if hasattr(event, "position") else event.pos()
            delta = cur - self._pan_last_pos
            self._pan_last_pos = cur
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self._pan_last_pos = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def zoom_in(self) -> None:
        factor = 1.2
        new_zoom = min(MAX_ZOOM, self._zoom * factor)
        ratio = new_zoom / self._zoom
        self.scale(ratio, ratio)
        self._zoom = new_zoom

    def zoom_out(self) -> None:
        factor = 1.2
        new_zoom = max(MIN_ZOOM, self._zoom / factor)
        ratio = new_zoom / self._zoom
        self.scale(ratio, ratio)
        self._zoom = new_zoom

    def reset_zoom(self) -> None:
        if self._zoom != 1.0:
            self.resetTransform()
            self._zoom = 1.0

    def fit_all(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.fitInView(rect, Qt.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def zoom_percent(self) -> int:
        return int(round(self._zoom * 100))
