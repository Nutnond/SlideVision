"""Magnetic-edges snap engine.

Computes a position delta to apply to a dragged `SlideItem` so that its
edges or center align with nearby siblings. Returns guide lines (in scene
coords) that the canvas can draw as visual feedback.

Axis-aligned bounding-box based. For rotated slides, falls back to
center-to-center snapping only (the math for rotated edge snapping is
significantly more complex and uncommon in stitching workflows).
"""

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, QLineF


@dataclass
class SnapResult:
    delta: QPointF = field(default_factory=lambda: QPointF(0, 0))
    guides: list[QLineF] = field(default_factory=list)
    snapped_x: bool = False
    snapped_y: bool = False


class SnapEngine:
    def __init__(self, threshold_scene: float = 8.0, max_threshold_scene: float = 50.0) -> None:
        # threshold_scene is auto-scaled with 1/canvas_zoom upstream, but cap
        # it to avoid over-eager snapping when zoomed far out.
        self._threshold = threshold_scene
        self._max_threshold = max_threshold_scene

    def threshold_for_zoom(self, canvas_zoom: float) -> float:
        """Convert screen-pixel threshold to scene units, capped."""
        if canvas_zoom <= 0:
            return self._max_threshold
        t = self._threshold / canvas_zoom
        return min(t, self._max_threshold)

    def compute(
        self,
        dragged_rect: QRectF,
        sibling_rects: list[QRectF],
        canvas_zoom: float,
    ) -> SnapResult:
        """Compute snap delta for `dragged_rect` against `sibling_rects`.
        All rects are AABBs in scene coords. Returns delta (in scene units)
        to add to the dragged item's position + guide lines to draw."""
        result = SnapResult()
        threshold = self.threshold_for_zoom(canvas_zoom)
        if not sibling_rects or threshold <= 0:
            return result

        d_left = dragged_rect.left()
        d_right = dragged_rect.right()
        d_top = dragged_rect.top()
        d_bottom = dragged_rect.bottom()
        d_cx = dragged_rect.center().x()
        d_cy = dragged_rect.center().y()

        best_dx: tuple[float, float, QLineF] | None = None  # (abs_delta, signed_delta, guide)
        best_dy: tuple[float, float, QLineF] | None = None

        for s in sibling_rects:
            s_left = s.left()
            s_right = s.right()
            s_top = s.top()
            s_bottom = s.bottom()
            s_cx = s.center().x()
            s_cy = s.center().y()

            # X candidates: edge-edge first (higher priority), then center-center.
            x_candidates: list[tuple[int, float, float]] = [
                # (priority, signed_delta, scene_x_to_mark)
                (0, s_left - d_left, s_left),
                (0, s_right - d_right, s_right),
                (0, s_left - d_right, s_left),  # dragged right edge → sibling left
                (0, s_right - d_left, s_right),  # dragged left edge → sibling right
                (1, s_cx - d_cx, s_cx),  # center align
            ]
            for prio, delta, mark_x in x_candidates:
                adelta = abs(delta)
                if adelta > threshold:
                    continue
                key = (prio, adelta)
                if best_dx is None or key < (best_dx[0], best_dx[1]):
                    y_top = min(dragged_rect.top(), s.top())
                    y_bot = max(dragged_rect.bottom(), s.bottom())
                    guide = QLineF(mark_x, y_top, mark_x, y_bot)
                    best_dx = (prio, adelta, delta, guide)

            y_candidates: list[tuple[int, float, float]] = [
                (0, s_top - d_top, s_top),
                (0, s_bottom - d_bottom, s_bottom),
                (0, s_top - d_bottom, s_top),
                (0, s_bottom - d_top, s_bottom),
                (1, s_cy - d_cy, s_cy),
            ]
            for prio, delta, mark_y in y_candidates:
                adelta = abs(delta)
                if adelta > threshold:
                    continue
                key = (prio, adelta)
                if best_dy is None or key < (best_dy[0], best_dy[1]):
                    x_left = min(dragged_rect.left(), s.left())
                    x_right = max(dragged_rect.right(), s.right())
                    guide = QLineF(x_left, mark_y, x_right, mark_y)
                    best_dy = (prio, adelta, delta, guide)

        if best_dx is not None:
            result.delta = QPointF(best_dx[2], result.delta.y())
            result.guides.append(best_dx[3])
            result.snapped_x = True
        if best_dy is not None:
            result.delta = QPointF(result.delta.x(), best_dy[2])
            result.guides.append(best_dy[3])
            result.snapped_y = True
        return result
