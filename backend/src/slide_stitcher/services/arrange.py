"""Auto-arrange algorithms for slide layout.

Pure functions — Qt-free. Operate on `SlidePosition` objects, returning new
lists with updated x/y. Width/height/rotation/crop are preserved.

Two algorithms:

- `arrange_grid` — N-column grid. Cell = current slide size. Rows
  left-aligned. Good for blocks A, B, C, D in a known order.

- `arrange_row_pack` — first-fit decreasing bin-pack by height. Rows of
  variable width; each row's height = tallest slide in it. Slides scaled
  to row height. Good for slides of varying aspect ratio.
"""

from slide_stitcher.models import SlidePosition


def arrange_grid(
    positions: list[SlidePosition],
    columns: int = 4,
    gap: float = 8.0,
    preserve_order: bool = True,
) -> list[SlidePosition]:
    """Lay out positions in a left-aligned grid with N columns.

    Each cell is sized to the slide's current w × h. Rows left-aligned.
    Slides keep their original size and rotation.
    """
    if not positions:
        return []
    if columns < 1:
        columns = 1

    items = list(positions)
    if not preserve_order:
        # Sort by aspect ratio (wider first) for visual balance.
        items.sort(key=lambda p: (-p.w / max(1.0, p.h), -p.h))

    out: list[SlidePosition] = []
    # Track column widths and per-row heights for tighter packing.
    col_widths = [0.0] * columns
    row_heights: list[float] = [0.0]
    item_grid_pos: list[tuple[int, int]] = []
    for i, pos in enumerate(items):
        col = i % columns
        row = i // columns
        if row >= len(row_heights):
            row_heights.append(0.0)
        col_widths[col] = max(col_widths[col], pos.w)
        row_heights[row] = max(row_heights[row], pos.h)
        item_grid_pos.append((col, row))

    # Cumulative column x-offsets.
    col_x = [0.0]
    for w in col_widths:
        col_x.append(col_x[-1] + w + gap)
    # Cumulative row y-offsets.
    row_y = [0.0]
    for h in row_heights:
        row_y.append(row_y[-1] + h + gap)

    for pos, (col, row) in zip(items, item_grid_pos):
        new_pos = pos.model_copy()
        new_pos.x = col_x[col]
        new_pos.y = row_y[row]
        out.append(new_pos)
    return out


def arrange_row_pack(
    positions: list[SlidePosition],
    target_row_height: float = 400.0,
    gap: float = 8.0,
    max_row_width: float | None = None,
) -> list[SlidePosition]:
    """First-fit decreasing bin-pack by height.

    Sort slides by height desc. For each slide, find the first row whose
    tallest slide is close in height (within 25% of slide's height). If
    none, start a new row. The `max_row_width` (default = sum of all widths)
    bounds when a new row must start.
    """
    if not positions:
        return []

    items = sorted(positions, key=lambda p: -p.h)
    if max_row_width is None:
        max_row_width = sum(p.w for p in items) + gap * len(items)

    rows: list[list[tuple[SlidePosition, float, float]]] = []  # (item, scaled_w, scaled_h)
    row_widths: list[float] = []
    row_heights: list[float] = []

    for pos in items:
        scaled_w = pos.w * (target_row_height / max(1.0, pos.h))
        scaled_h = target_row_height
        placed = False
        for i, rh in enumerate(row_heights):
            if abs(rh - scaled_h) <= 0.25 * scaled_h and row_widths[i] + gap + scaled_w <= max_row_width:
                rows[i].append((pos, scaled_w, scaled_h))
                row_widths[i] += gap + scaled_w
                row_heights[i] = max(rh, scaled_h)
                placed = True
                break
        if not placed:
            rows.append([(pos, scaled_w, scaled_h)])
            row_widths.append(scaled_w)
            row_heights.append(scaled_h)

    # Lay out rows top-to-bottom, items left-to-right.
    out: list[SlidePosition] = []
    y = 0.0
    for row, row_width, row_height in zip(rows, row_widths, row_heights):
        # Center each row's content within max_row_width for visual balance.
        x = max(0.0, (max_row_width - row_width) / 2.0)
        for pos, scaled_w, scaled_h in row:
            new_pos = pos.model_copy()
            new_pos.x = x
            new_pos.y = y
            new_pos.w = scaled_w
            new_pos.h = scaled_h
            out.append(new_pos)
            x += scaled_w + gap
        y += row_height + gap
    return out
