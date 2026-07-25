from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from slide_stitcher.models import SlideMetadata, SlidePosition
from slide_stitcher.ui.widgets.slide_item import SlideItem
from slide_stitcher.ui.widgets.snap_engine import SnapEngine

DEFAULT_DISPLAY_MAX = 400.0

# Discrete magnification stops (microscope objective metaphor).
# Canvas zoom snaps to these — free zoom only allowed momentarily during a
# pinch gesture, then snaps to the nearest stop on release.
ZOOM_STOPS: list[float] = [1.0, 2.0, 4.0, 10.0, 20.0, 40.0]
ZOOM_LABELS: list[str] = ["1×", "2×", "4×", "10×", "20×", "40×"]


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
    zoomChanged = Signal(int, str)  # (zoom_index, label)
    cursorSlideChanged = Signal(object)  # slide_id under cursor or None
    viewportChanged = Signal()  # pan / scroll / resize — triggers tile reload

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
        self._zoom: float = 1.0           # actual transform scale (may drift between stops during pinch)
        self._zoom_index: int = 0         # index into ZOOM_STOPS — the committed magnification
        self._panning = False
        self._pan_last_pos = None
        self._cursor_slide_id: str | None = None

        # Magnetic-edges infrastructure (Phase 4).
        self._snap_engine = SnapEngine()
        self._magnetic_enabled = True
        self._snap_guides: list[QLineF] = []

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

    def apply_positions(self, positions: list[SlidePosition]) -> None:
        """Apply new positions to existing items (used by Auto-Arrange).
        Updates only x/y/w/h; rotation and crop are preserved as-is on the
        item (arrange functions may overwrite w/h via row_pack)."""
        for pos in positions:
            item = self._items_by_id.get(pos.id)
            if item is None:
                continue
            item.set_geometry(pos.x, pos.y, pos.w, pos.h)
        # Re-trigger tile overlay computation since geometry changed.
        self.viewportChanged.emit()

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
        # Plain wheel/trackpad scroll = pan. Cmd+wheel = snap one magnification stop.
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self._snap_zoom(self._zoom_index + 1)
            else:
                self._snap_zoom(self._zoom_index - 1)
            event.accept()
            return
        super().wheelEvent(event)
        self.viewportChanged.emit()

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
        sf = pinch.scaleFactor()
        if abs(sf - 1.0) < 1e-3:
            return
        center_viewport = self.mapFromGlobal(pinch.centerPoint().toPoint())
        center_scene = self.mapToScene(center_viewport)

        # Free scaling during gesture (feels smoother than discrete steps).
        lo, hi = ZOOM_STOPS[0] / 2.0, ZOOM_STOPS[-1] * 2.0
        new_zoom = max(lo, min(hi, self._zoom * sf))
        ratio = new_zoom / self._zoom
        self.scale(ratio, ratio)
        self._zoom = new_zoom

        # Re-anchor on the gesture center
        new_center_viewport = self.mapFromScene(center_scene)
        delta = new_center_viewport - center_viewport
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta.y())

        # Track nearest stop so label updates during gesture.
        nearest = self._nearest_stop_index(self._zoom)
        if nearest != self._zoom_index:
            self._zoom_index = nearest
            self._emit_zoom_changed()

        if pinch.state() == Qt.GestureEnded:
            # Snap transform to the nearest stop.
            self._snap_zoom(self._nearest_stop_index(self._zoom), keep_zoom=False)
        self.viewportChanged.emit()

    @staticmethod
    def _nearest_stop_index(zoom: float) -> int:
        best = 0
        best_dist = abs(ZOOM_STOPS[0] - zoom)
        for i, s in enumerate(ZOOM_STOPS[1:], start=1):
            d = abs(s - zoom)
            if d < best_dist:
                best_dist = d
                best = i
        return best

    def _snap_zoom(self, target_index: int, keep_zoom: bool = False) -> None:
        """Snap to ZOOM_STOPS[target_index]. If keep_zoom is True (gesture
        end), the call also accepts the current free-zoom factor as the new
        baseline before snapping."""
        target_index = max(0, min(len(ZOOM_STOPS) - 1, target_index))
        target = ZOOM_STOPS[target_index]
        if abs(target - self._zoom) > 1e-6:
            ratio = target / self._zoom
            self.scale(ratio, ratio)
            self._zoom = target
        if self._zoom_index != target_index:
            self._zoom_index = target_index
            self._emit_zoom_changed()
        self.viewportChanged.emit()

    def _emit_zoom_changed(self) -> None:
        self.zoomChanged.emit(self._zoom_index, ZOOM_LABELS[self._zoom_index])

    def zoom_in(self) -> None:
        self._snap_zoom(self._zoom_index + 1)

    def zoom_out(self) -> None:
        self._snap_zoom(self._zoom_index - 1)

    def set_zoom_index(self, index: int) -> None:
        self._snap_zoom(index)

    def reset_zoom(self) -> None:
        self._snap_zoom(0)

    def fit_all(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.fitInView(rect, Qt.KeepAspectRatio)
        self._zoom = self.transform().m11()
        # Snap to nearest stop.
        self._snap_zoom(self._nearest_stop_index(self._zoom))

    # --- accessors used by status bar / external code ---

    def current_zoom_index(self) -> int:
        return self._zoom_index

    def current_zoom_label(self) -> str:
        return ZOOM_LABELS[self._zoom_index]

    def current_zoom_factor(self) -> float:
        return self._zoom

    def zoom_percent(self) -> int:
        # Kept for backward compat with code that reads it (legacy %).
        return int(round(self._zoom * 100))

    # --- cursor / slide-under-cursor tracking ---

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
            self.viewportChanged.emit()
            return
        super().mouseMoveEvent(event)
        self._track_cursor_slide(event)

    def _track_cursor_slide(self, event) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        item = self.itemAt(pos)
        slide_id: str | None = None
        if isinstance(item, SlideItem):
            slide_id = item.slide_id
        if slide_id != self._cursor_slide_id:
            self._cursor_slide_id = slide_id
            self.cursorSlideChanged.emit(slide_id)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.viewportChanged.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.viewportChanged.emit()

    # --- magnetic edges (Phase 4) ---

    def set_magnetic_enabled(self, enabled: bool) -> None:
        self._magnetic_enabled = enabled
        if not enabled:
            self._snap_guides.clear()
            self.viewport().update()

    def is_magnetic_enabled(self) -> bool:
        return self._magnetic_enabled

    def compute_snap(self, dragged: "SlideItem", proposed_pos: QPointF) -> tuple[QPointF, list[QLineF]]:
        """Compute snap-adjusted position for `dragged` if it were at `proposed_pos`.
        Returns (adjusted_pos, guides). Caller is responsible for applying."""
        if not self._magnetic_enabled:
            return proposed_pos, []
        # Build dragged rect at proposed position.
        dragged_rect = QRectF(proposed_pos.x(), proposed_pos.y(), dragged._w, dragged._h)
        siblings: list[QRectF] = []
        for sid, item in self._items_by_id.items():
            if sid == dragged.slide_id:
                continue
            siblings.append(item.sceneBoundingRect())
        if not siblings:
            return proposed_pos, []
        result = self._snap_engine.compute(dragged_rect, siblings, self._zoom)
        adjusted = QPointF(proposed_pos.x() + result.delta.x(), proposed_pos.y() + result.delta.y())
        return adjusted, result.guides

    def set_snap_guides(self, guides: list[QLineF]) -> None:
        self._snap_guides = guides
        self.viewport().update()

    def clear_snap_guides(self) -> None:
        if self._snap_guides:
            self._snap_guides.clear()
            self.viewport().update()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        if not self._snap_guides:
            return
        painter.save()
        pen = QPen(QColor("#ff9800"), 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for line in self._snap_guides:
            painter.drawLine(line)
        painter.restore()

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

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self._pan_last_pos = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

