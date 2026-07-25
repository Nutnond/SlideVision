"""Overlay minimap showing where the current viewport sits within the case.

Renders all on-canvas slide thumbnails at low-res plus a viewport rectangle
indicating the currently-visible region. Click anywhere on the minimap to
recenter the canvas; click-drag inside the viewport rect to pan.

Intended to live as an overlay child of MainWindow, positioned in the
bottom-right corner of the canvas viewport.
"""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

PAD = 8  # padding around minimap content


class MiniMap(QWidget):
    def __init__(self, canvas, parent=None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self.setFixedSize(220, 160)
        self.setWindowTitle("MiniMap")
        # Transparent widget — we paint background ourselves.
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self._case_bounds: QRectF | None = None
        self._viewport_rect_scene: QRectF | None = None
        self._dragging = False
        self._show_viewport_only_when_zoomed = True  # hide rect at zoom=1

    def update_from_canvas(self) -> None:
        """Recompute case bounds + viewport rect from canvas state."""
        items_rect = self._canvas.scene.itemsBoundingRect()
        # Inflate slightly so a single off-center slide isn't edge-to-edge.
        if not items_rect.isEmpty():
            items_rect = items_rect.adjusted(-20, -20, 20, 20)
        self._case_bounds = items_rect
        viewport = self._canvas.viewport().rect()
        # mapToScene(QRect) → QPolygonF → boundingRect
        self._viewport_rect_scene = self._canvas.mapToScene(viewport).boundingRect()
        self.update()

    # --- geometry mapping ---

    def _map_to_minimap(self, scene_rect: QRectF) -> QRectF:
        if self._case_bounds is None or self._case_bounds.isEmpty():
            return QRectF()
        target = QRectF(self.rect()).adjusted(PAD, PAD, -PAD, -PAD)
        scale_x = target.width() / self._case_bounds.width()
        scale_y = target.height() / self._case_bounds.height()
        scale = min(scale_x, scale_y)
        # Center the case inside the minimap target area.
        content_w = self._case_bounds.width() * scale
        content_h = self._case_bounds.height() * scale
        off_x = target.x() + (target.width() - content_w) / 2
        off_y = target.y() + (target.height() - content_h) / 2
        return QRectF(
            off_x + (scene_rect.x() - self._case_bounds.x()) * scale,
            off_y + (scene_rect.y() - self._case_bounds.y()) * scale,
            scene_rect.width() * scale,
            scene_rect.height() * scale,
        )

    def _map_to_scene(self, minimap_pos: QPointF) -> QPointF:
        if self._case_bounds is None or self._case_bounds.isEmpty():
            return QPointF()
        target = QRectF(self.rect()).adjusted(PAD, PAD, -PAD, -PAD)
        scale_x = target.width() / self._case_bounds.width()
        scale_y = target.height() / self._case_bounds.height()
        scale = min(scale_x, scale_y)
        content_w = self._case_bounds.width() * scale
        content_h = self._case_bounds.height() * scale
        off_x = target.x() + (target.width() - content_w) / 2
        off_y = target.y() + (target.height() - content_h) / 2
        return QPointF(
            self._case_bounds.x() + (minimap_pos.x() - off_x) / scale,
            self._case_bounds.y() + (minimap_pos.y() - off_y) / scale,
        )

    # --- painting ---

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # Background panel
        painter.setBrush(QColor(15, 23, 42, 220))
        painter.setPen(QPen(QColor("#475569"), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)

        if self._case_bounds is None or self._case_bounds.isEmpty():
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.rect(), Qt.AlignCenter, "No slides")
            return

        # Draw each slide's thumbnail (low-res).
        for sid, item in self._canvas._items_by_id.items():
            item_rect_scene = item.sceneBoundingRect()
            if not self._case_bounds.intersects(item_rect_scene):
                continue
            mm_rect = self._map_to_minimap(item_rect_scene)
            if mm_rect.isEmpty():
                continue
            if not item.pixmap.isNull():
                painter.drawPixmap(
                    mm_rect,
                    item.pixmap,
                    QRectF(0, 0, item.pixmap.width(), item.pixmap.height()),
                )
            painter.setPen(QPen(QColor("#1e293b"), 0.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(mm_rect)

        # Viewport rectangle (current visible region).
        if self._viewport_rect_scene is not None and not self._viewport_rect_scene.isEmpty():
            zoom = self._canvas.current_zoom_factor()
            # Show the rect always (even at zoom=1, it indicates the visible region).
            _ = zoom  # kept for future tweakability
            vp = self._map_to_minimap(self._viewport_rect_scene)
            painter.setBrush(QColor(251, 191, 36, 50))
            painter.setPen(QPen(QColor("#fbbf24"), 1.5))
            painter.drawRect(vp)

    # --- interaction ---

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._dragging = True
        self._recenter_canvas(event.position())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        self._recenter_canvas(event.position())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        event.accept()

    def _recenter_canvas(self, minimap_pos: QPointF) -> None:
        scene_pt = self._map_to_scene(minimap_pos)
        if scene_pt.isNull():
            return
        self._canvas.centerOn(QPointF(scene_pt.x(), scene_pt.y()))
