import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsObject, QGraphicsSceneMouseEvent, QStyle

HANDLE_SIZE = 10
ROT_HANDLE_DISTANCE = 28.0
MIN_SIZE = 20.0


class SlideItem(QGraphicsObject):
    moved = Signal(str, float, float)
    resized = Signal(str, float, float, float, float)
    rotated = Signal(str, float)
    cropped = Signal(str)
    selected_changed = Signal(str, bool)

    def __init__(self, slide_id: str, pixmap: QPixmap, parent=None) -> None:
        super().__init__(parent)
        self.slide_id = slide_id
        self.pixmap = pixmap
        self._w: float = float(pixmap.width())
        self._h: float = float(pixmap.height())
        self._rotation: float = 0.0
        self._crop_x: float = 0.0
        self._crop_y: float = 0.0
        self._crop_w: float = 1.0
        self._crop_h: float = 1.0

        self._crop_x: float = 0.0
        self._crop_y: float = 0.0
        self._crop_w: float = 1.0
        self._crop_h: float = 1.0
        # Cumulative applied crop in original normalized coords (compounded across multiple applies)
        self._applied_x: float = 0.0
        self._applied_y: float = 0.0
        self._applied_w: float = 1.0
        self._applied_h: float = 1.0

        self._active_handle: str | None = None
        self._drag_start: dict | None = None
        self._user_dragging: bool = False  # body drag (not handle) — gates magnetic snap
        self._snap_applied_this_drag: bool = False  # avoid feedback loop in itemChange

        # Hi-res tile overlay state (deep zoom). When enabled, tiles paint on
        # top of the low-res thumbnail pixmap to reveal native WSI detail.
        # _tile_config: dict with keys (level, pixel_w, pixel_h, tile_size)
        # _tiles: dict[(origin_x_native, origin_y_native)] -> QPixmap
        self._tile_config: dict | None = None
        self._tiles: dict[tuple[int, int], QPixmap] = {}
        self._show_tiles: bool = False  # gated by zoom level + not dragging
        self._tiles_enabled: bool = True  # master toggle (e.g. disabled during handle drag)

        self.setFlag(QGraphicsObject.ItemIsMovable, True)
        self.setFlag(QGraphicsObject.ItemIsSelectable, True)
        self.setFlag(QGraphicsObject.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsObject.ItemIsFocusable, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.SizeAllCursor)
        self.setTransformOriginPoint(self._w / 2, self._h / 2)

    def boundingRect(self) -> QRectF:
        return QRectF(
            -HANDLE_SIZE / 2,
            -HANDLE_SIZE / 2 - ROT_HANDLE_DISTANCE,
            self._w + HANDLE_SIZE,
            self._h + HANDLE_SIZE + ROT_HANDLE_DISTANCE,
        )

    def shape(self):
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        path.addRect(QRectF(0, 0, self._w, self._h))
        if self.isSelected():
            for rect in self._corner_handle_rects().values():
                path.addRect(rect)
            path.addEllipse(self._rotate_handle_rect())
            for rect in self._crop_edge_handles().values():
                path.addRect(rect)
        return path

    def paint(self, painter, option, widget=None) -> None:
        option.state &= ~QStyle.State_Selected

        if not self.pixmap.isNull():
            painter.drawPixmap(
                QRectF(0, 0, self._w, self._h),
                self.pixmap,
                QRectF(0, 0, self.pixmap.width(), self.pixmap.height()),
            )

        # Hi-res tile overlay — paints native-resolution tiles on top of the
        # thumbnail when zoomed in past thumbnail density. Tile (ox, oy) is in
        # native WSI pixels; we map to slide-local coords via pixel_w/pixel_h.
        if self._show_tiles and self._tiles_enabled and self._tile_config and self._tiles:
            cfg = self._tile_config
            px_w = max(1, cfg["pixel_w"])
            px_h = max(1, cfg["pixel_h"])
            tile_native = cfg["tile_size"]
            scale_x = self._w / px_w
            scale_y = self._h / px_h
            tw = tile_native * scale_x
            th = tile_native * scale_y
            for (ox, oy), tile_pixmap in self._tiles.items():
                if tile_pixmap.isNull():
                    continue
                x = ox * scale_x
                y = oy * scale_y
                painter.drawPixmap(
                    QRectF(x, y, tw, th),
                    tile_pixmap,
                    QRectF(0, 0, tile_pixmap.width(), tile_pixmap.height()),
                )

        painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(0, 0, self._w, self._h))

        has_crop = self._crop_w < 1.0 or self._crop_h < 1.0
        if has_crop:
            cx = self._crop_x * self._w
            cy = self._crop_y * self._h
            cw = self._crop_w * self._w
            ch = self._crop_h * self._h

            dim = QColor(0, 0, 0, 150)
            painter.setBrush(dim)
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(0, 0, self._w, cy))
            painter.drawRect(QRectF(0, cy + ch, self._w, self._h - (cy + ch)))
            painter.drawRect(QRectF(0, cy, cx, ch))
            painter.drawRect(QRectF(cx + cw, cy, self._w - (cx + cw), ch))

            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#1976d2"), 1.2))
            painter.drawRect(QRectF(cx, cy, cw, ch))

        if self.isSelected():
            painter.setPen(QPen(QColor("#1976d2"), 1.5))
            painter.drawRect(QRectF(0, 0, self._w, self._h).adjusted(-1, -1, 1, 1))

            cx = self._w / 2
            painter.setPen(QPen(QColor("#1976d2"), 1))
            painter.drawLine(QPointF(cx, 0), QPointF(cx, -ROT_HANDLE_DISTANCE))

            painter.setBrush(QBrush(QColor("white")))
            painter.setPen(QPen(QColor("#1976d2"), 1))
            for rect in self._corner_handle_rects().values():
                painter.drawRect(rect)

            rot_rect = self._rotate_handle_rect()
            painter.setBrush(QBrush(QColor("#1976d2")))
            painter.drawEllipse(rot_rect)

            # Always show crop edge handles (orange) so user can drag them directly
            painter.setBrush(QBrush(QColor("#ff9800")))
            painter.setPen(QPen(QColor("white"), 1))
            for rect in self._crop_edge_handles().values():
                painter.drawRect(rect)

    def _corner_handle_rects(self) -> dict[str, QRectF]:
        s = HANDLE_SIZE
        return {
            "tl": QRectF(-s / 2, -s / 2, s, s),
            "tr": QRectF(self._w - s / 2, -s / 2, s, s),
            "bl": QRectF(-s / 2, self._h - s / 2, s, s),
            "br": QRectF(self._w - s / 2, self._h - s / 2, s, s),
        }

    def _rotate_handle_rect(self) -> QRectF:
        s = HANDLE_SIZE
        return QRectF(
            self._w / 2 - s / 2,
            -ROT_HANDLE_DISTANCE - s / 2,
            s,
            s,
        )

    def _crop_edge_handles(self) -> dict[str, QRectF]:
        s = HANDLE_SIZE
        cx = self._crop_x * self._w
        cy = self._crop_y * self._h
        cw = self._crop_w * self._w
        ch = self._crop_h * self._h
        return {
            "ce_t": QRectF(cx + cw / 2 - s / 2, cy - s / 2, s, s),
            "ce_b": QRectF(cx + cw / 2 - s / 2, cy + ch - s / 2, s, s),
            "ce_l": QRectF(cx - s / 2, cy + ch / 2 - s / 2, s, s),
            "ce_r": QRectF(cx + cw - s / 2, cy + ch / 2 - s / 2, s, s),
        }

    def _handle_at(self, pos: QPointF) -> str | None:
        if not self.isSelected():
            return None
        for hid, rect in self._corner_handle_rects().items():
            if rect.contains(pos):
                return hid
        if self._rotate_handle_rect().contains(pos):
            return "rot"
        # Crop edges always available when selected
        for hid, rect in self._crop_edge_handles().items():
            if rect.contains(pos):
                return hid
        return None

    def hoverMoveEvent(self, event) -> None:
        h = self._handle_at(event.pos())
        if h == "rot":
            self.setCursor(Qt.CrossCursor)
        elif h in ("ce_t", "ce_b"):
            self.setCursor(Qt.SizeVerCursor)
        elif h in ("ce_l", "ce_r"):
            self.setCursor(Qt.SizeHorCursor)
        elif h:
            cursor = Qt.SizeFDiagCursor if h in ("tl", "br") else Qt.SizeBDiagCursor
            self.setCursor(cursor)
        else:
            self.setCursor(Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        h = self._handle_at(event.pos())
        if h and event.button() == Qt.LeftButton:
            self._active_handle = h
            self._drag_start = {
                "scene_pos": event.scenePos(),
                "item_pos": QPointF(self.pos()),
                "w": self._w,
                "h": self._h,
                "rotation": self._rotation,
                "crop_x": self._crop_x,
                "crop_y": self._crop_y,
                "crop_w": self._crop_w,
                "crop_h": self._crop_h,
            }
            self.suspend_tiles_for_drag()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            # Body drag (not handle) — enable magnetic snap.
            self._user_dragging = True
            self._snap_applied_this_drag = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._active_handle and self._drag_start:
            if self._active_handle == "rot":
                self._do_rotate(event.scenePos())
            elif self._active_handle.startswith("ce_"):
                self._do_crop_drag(event.scenePos())
            else:
                self._do_resize(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._active_handle:
            h = self._active_handle
            self._active_handle = None
            self._drag_start = None
            if h == "rot":
                self.rotated.emit(self.slide_id, self._rotation)
            elif h.startswith("ce_"):
                self.cropped.emit(self.slide_id)
            else:
                self.resized.emit(self.slide_id, self.pos().x(), self.pos().y(), self._w, self._h)
            self.restore_tiles_after_drag()
            self.update()
            event.accept()
            return
        if self._user_dragging:
            self._user_dragging = False
            self._snap_applied_this_drag = False
            # Clear snap guides on release.
            for view in self.scene().views():
                if hasattr(view, "clear_snap_guides"):
                    view.clear_snap_guides()
        super().mouseReleaseEvent(event)

    def _scene_to_local_delta(self, scene_delta: QPointF) -> QPointF:
        if self._rotation == 0:
            return scene_delta
        tr = QTransform().rotate(-self._rotation)
        return tr.map(scene_delta)

    def _do_resize(self, scene_pos: QPointF) -> None:
        s = self._drag_start
        scene_delta = scene_pos - s["scene_pos"]
        d = self._scene_to_local_delta(scene_delta)
        dx, dy = d.x(), d.y()
        h = self._active_handle

        new_w = s["w"]
        new_h = s["h"]
        new_x = s["item_pos"].x()
        new_y = s["item_pos"].y()

        if h in ("tl", "bl"):
            new_w = s["w"] - dx
        elif h in ("tr", "br"):
            new_w = s["w"] + dx
        if h in ("tl", "tr"):
            new_h = s["h"] - dy
        elif h in ("bl", "br"):
            new_h = s["h"] + dy

        # When dragging TL/BL/TR handle on rotated item, the item's top-left in scene
        # moves so that the OPPOSITE corner stays fixed. Compute offset in scene coords.
        opp_local: QPointF
        if h == "tl":
            opp_local = QPointF(s["w"], s["h"])
        elif h == "tr":
            opp_local = QPointF(0, s["h"])
        elif h == "bl":
            opp_local = QPointF(s["w"], 0)
        else:  # br
            opp_local = QPointF(0, 0)

        # Position of opposite corner in scene coords (at start of drag)
        tr_start = QTransform().rotate(s["rotation"])
        opp_scene_offset = tr_start.map(opp_local)
        opp_scene_start = QPointF(
            s["item_pos"].x() + opp_scene_offset.x(),
            s["item_pos"].y() + opp_scene_offset.y(),
        )

        # Clamp size
        clamped_w = max(MIN_SIZE, new_w)
        clamped_h = max(MIN_SIZE, new_h)

        # Reconstruct: where should the new opposite corner (same scene point) map to in item-local coords?
        new_opp_local = {
            "tl": QPointF(clamped_w, clamped_h),
            "tr": QPointF(0, clamped_h),
            "bl": QPointF(clamped_w, 0),
            "br": QPointF(0, 0),
        }[h]

        tr_new = QTransform().rotate(self._rotation)
        new_opp_scene_offset = tr_new.map(new_opp_local)
        new_pos = QPointF(
            opp_scene_start.x() - new_opp_scene_offset.x(),
            opp_scene_start.y() - new_opp_scene_offset.y(),
        )

        self.prepareGeometryChange()
        self._w = clamped_w
        self._h = clamped_h
        self.setTransformOriginPoint(self._w / 2, self._h / 2)
        self.setPos(new_pos)

    def _do_rotate(self, scene_pos: QPointF) -> None:
        s = self._drag_start
        center_scene = QPointF(
            s["item_pos"].x() + s["w"] / 2,
            s["item_pos"].y() + s["h"] / 2,
        )
        v = scene_pos - center_scene
        angle = math.degrees(math.atan2(v.x(), -v.y()))
        if import_shift_held():
            angle = round(angle / 15) * 15
        self._rotation = angle
        self.setRotation(angle)
        self.update()

    def _do_crop_drag(self, scene_pos: QPointF) -> None:
        s = self._drag_start
        scene_delta = scene_pos - s["scene_pos"]
        local = self._scene_to_local_delta(scene_delta)
        # Normalize to slide display size
        dx = local.x() / max(1.0, self._w)
        dy = local.y() / max(1.0, self._h)

        crop_x = s["crop_x"]
        crop_y = s["crop_y"]
        crop_w = s["crop_w"]
        crop_h = s["crop_h"]

        h = self._active_handle
        if h == "ce_t":
            new_y = max(0.0, min(crop_y + crop_h - 0.05, crop_y + dy))
            crop_h = crop_h + (crop_y - new_y)
            crop_y = new_y
        elif h == "ce_b":
            crop_h = max(0.05, min(1.0 - crop_y, crop_h + dy))
        elif h == "ce_l":
            new_x = max(0.0, min(crop_x + crop_w - 0.05, crop_x + dx))
            crop_w = crop_w + (crop_x - new_x)
            crop_x = new_x
        elif h == "ce_r":
            crop_w = max(0.05, min(1.0 - crop_x, crop_w + dx))

        self.prepareGeometryChange()
        self._crop_x = crop_x
        self._crop_y = crop_y
        self._crop_w = crop_w
        self._crop_h = crop_h
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsObject.ItemPositionHasChanged:
            # Magnetic snap: only during interactive body drag, not programmatic moves.
            if self._user_dragging and not self._snap_applied_this_drag:
                canvas = None
                for view in self.scene().views():
                    if hasattr(view, "compute_snap"):
                        canvas = view
                        break
                if canvas is not None and canvas.is_magnetic_enabled():
                    proposed = QPointF(value.x(), value.y())
                    adjusted, guides = canvas.compute_snap(self, proposed)
                    canvas.set_snap_guides(guides)
                    if adjusted != proposed:
                        # Apply the snap. Set flag to suppress re-entrant snap on
                        # the position-change this triggers.
                        self._snap_applied_this_drag = True
                        self.setPos(adjusted)
                        self._snap_applied_this_drag = False
                        # After snapping, subsequent drags within threshold should
                        # re-snap — keep flag reset.
                        value = adjusted
            self.moved.emit(self.slide_id, value.x(), value.y())
        elif change == QGraphicsObject.ItemSelectedHasChanged:
            self.selected_changed.emit(self.slide_id, bool(value))
        return super().itemChange(change, value)

    def set_geometry(self, x: float, y: float, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._w = w
        self._h = h
        self.setTransformOriginPoint(self._w / 2, self._h / 2)
        self.setPos(x, y)

    def set_rotation(self, degrees: float) -> None:
        self._rotation = degrees
        self.setRotation(degrees)
        self.update()

    def set_crop(self, cx: float, cy: float, cw: float, ch: float) -> None:
        self.prepareGeometryChange()
        self._crop_x = max(0.0, min(1.0, cx))
        self._crop_y = max(0.0, min(1.0, cy))
        self._crop_w = max(0.01, min(1.0 - self._crop_x, cw))
        self._crop_h = max(0.01, min(1.0 - self._crop_y, ch))
        self.update()
        self.cropped.emit(self.slide_id)

    def apply_crop(self) -> bool:
        """Commit the current visual crop: shrink slide to the cropped region.
        Returns True if a crop was applied, False if no crop was set."""
        if self._crop_w >= 1.0 and self._crop_h >= 1.0:
            return False

        pw = self.pixmap.width()
        ph = self.pixmap.height()
        sx = int(self._crop_x * pw)
        sy = int(self._crop_y * ph)
        sw = max(1, int(self._crop_w * pw))
        sh = max(1, int(self._crop_h * ph))
        new_pixmap = self.pixmap.copy(sx, sy, sw, sh)

        new_w = self._w * self._crop_w
        new_h = self._h * self._crop_h

        tr = QTransform().rotate(self._rotation)
        local_offset = QPointF(self._crop_x * self._w, self._crop_y * self._h)
        scene_offset = tr.map(local_offset)
        new_x = self.pos().x() + scene_offset.x()
        new_y = self.pos().y() + scene_offset.y()

        self.prepareGeometryChange()
        self.pixmap = new_pixmap
        self._w = new_w
        self._h = new_h
        self.setPos(new_x, new_y)
        self.setTransformOriginPoint(new_w / 2, new_h / 2)

        applied_dx = self._crop_x
        applied_dy = self._crop_y
        applied_dw = self._crop_w
        applied_dh = self._crop_h

        self._crop_x = 0.0
        self._crop_y = 0.0
        self._crop_w = 1.0
        self._crop_h = 1.0

        # Compound into cumulative applied crop
        self._applied_x = self._applied_x + applied_dx * self._applied_w
        self._applied_y = self._applied_y + applied_dy * self._applied_h
        self._applied_w = self._applied_w * applied_dw
        self._applied_h = self._applied_h * applied_dh

        self.update()
        self.resized.emit(self.slide_id, new_x, new_y, new_w, new_h)
        self.cropped.emit(self.slide_id)
        # Pixmap replaced → tile geometry invalid, clear overlay.
        self.clear_tiles()
        self.set_tile_overlay_enabled(False)
        return True

    def pop_last_applied_delta(self) -> tuple[float, float, float, float] | None:
        return None

    def get_crop(self) -> tuple[float, float, float, float]:
        return self._crop_x, self._crop_y, self._crop_w, self._crop_h

    def get_applied_crop(self) -> tuple[float, float, float, float]:
        return self._applied_x, self._applied_y, self._applied_w, self._applied_h

    def set_applied_crop(self, ax: float, ay: float, aw: float, ah: float) -> None:
        self._applied_x = ax
        self._applied_y = ay
        self._applied_w = aw
        self._applied_h = ah

    def current_geometry(self) -> tuple[float, float, float, float]:
        return self.pos().x(), self.pos().y(), self._w, self._h

    # --- tile overlay API (used by canvas + TileLoader) ---

    def set_tile_config(self, config: dict | None) -> None:
        """Set or clear the tile geometry config. Tiles are only cleared when
        a meaningful field changes (level, pixel_w/h, tile_size, applied_offset)
        — panning the canvas does NOT invalidate already-loaded tiles."""
        old = self._tile_config
        if config is None:
            if old is not None:
                self._tile_config = None
                self._tiles.clear()
                self.update()
            return
        if old is not None and all(old.get(k) == config.get(k) for k in (
            "level", "pixel_w", "pixel_h", "tile_size",
            "applied_offset_x", "applied_offset_y",
        )):
            # No meaningful change — keep loaded tiles.
            return
        self._tile_config = config
        self._tiles.clear()
        self.update()

    def set_tile_overlay_enabled(self, enabled: bool) -> None:
        """Master on/off for the hi-res overlay (gated by zoom density)."""
        if self._show_tiles != enabled:
            self._show_tiles = enabled
            self.update()

    def set_tile_pixmap(self, origin_x_native: int, origin_y_native: int, pixmap: QPixmap) -> None:
        self._tiles[(origin_x_native, origin_y_native)] = pixmap
        if self._show_tiles and self._tiles_enabled:
            self.update()

    def clear_tiles(self) -> None:
        if self._tiles:
            self._tiles.clear()
            self.update()

    def suspend_tiles_for_drag(self) -> None:
        """Hide overlay during interactive handle drag (prevents flicker from
        stale tiles while geometry changes)."""
        if self._tiles_enabled:
            self._tiles_enabled = False
            self.update()

    def restore_tiles_after_drag(self) -> None:
        if not self._tiles_enabled:
            self._tiles_enabled = True
            self.update()


def import_shift_held() -> bool:
    from PySide6.QtGui import QGuiApplication

    mods = QGuiApplication.queryKeyboardModifiers()
    return bool(mods & Qt.ShiftModifier)
