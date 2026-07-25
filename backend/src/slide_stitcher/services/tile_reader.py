"""Tile reader for deep-zoom rendering.

Pure function API — no Qt imports. Designed to be called from any thread
(including non-Qt workers). Returns PNG bytes so results can cross thread
boundaries safely; the UI layer converts to QPixmap.
"""

import io
from dataclasses import dataclass
from pathlib import Path

from slide_stitcher.services.wsi_cache import WSIHandleCache


@dataclass(frozen=True)
class TileRequest:
    slide_path: Path
    region_origin: tuple[int, int]  # (x, y) in level-0 pixels
    level: int                      # OpenSlide pyramid level (0 = full res)
    region_size: tuple[int, int]    # (w, h) at the requested level


def read_tile(req: TileRequest, cache: WSIHandleCache) -> bytes | None:
    """Read a single tile from a WSI. Returns PNG bytes, or None if the slide
    cannot be opened or the read fails."""
    slide = cache.get(req.slide_path)
    if slide is None:
        return None
    try:
        img = slide.read_region(req.region_origin, req.level, req.region_size)
        rgb = img.convert("RGB")
        with io.BytesIO() as buf:
            rgb.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        print(f"[tile_reader] failed level={req.level} origin={req.region_origin} size={req.region_size}: {e}")
        return None


def pick_level_for_downsample(
    level_downsamples: list[float],
    target_downsample: float,
) -> int:
    """Pick the pyramid level whose downsample is closest to (but not greater
    than when possible) the target. Returns 0 if no pyramid info available."""
    if not level_downsamples:
        return 0
    # Find the largest level whose downsample <= target (so we don't lose detail
    # by reading too-downsampled a level). Fall back to the closest if all
    # exceed the target.
    best = 0
    for i, d in enumerate(level_downsamples):
        if d <= target_downsample:
            best = i
        else:
            break
    return best
