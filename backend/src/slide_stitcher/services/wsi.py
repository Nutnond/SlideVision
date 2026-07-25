import io
from pathlib import Path

import openslide

from slide_stitcher.services.thumbnail import generate_image_thumbnail
from slide_stitcher.services.types import ThumbResult

WSI_EXTENSIONS = {".svs", ".ndpi", ".mrxs", ".vms", ".scn", ".bif", ".tif", ".tiff"}


def try_open_wsi(path: Path) -> openslide.OpenSlide | None:
    try:
        return openslide.open_slide(str(path))
    except openslide.OpenSlideError:
        return None
    except OSError:
        return None
    except Exception:
        return None


def _extract_wsi_metadata(slide: openslide.OpenSlide) -> dict:
    """Read magnification-related properties. Returns dict with None / empty defaults
    when properties are absent. Wrapped in try/except — different vendors expose
    different subsets and we don't want metadata extraction to fail the thumbnail."""
    out: dict = {
        "mpp_x": None,
        "mpp_y": None,
        "objective_power": None,
        "level_count": 0,
        "level_downsamples": [],
        "level_dimensions": [],
    }
    try:
        props = slide.properties
        mpp_x = props.get(openslide.PROPERTY_NAME_MPP_X)
        mpp_y = props.get(openslide.PROPERTY_NAME_MPP_Y)
        if mpp_x is not None:
            out["mpp_x"] = float(mpp_x)
        if mpp_y is not None:
            out["mpp_y"] = float(mpp_y)
    except Exception:
        pass
    try:
        op = slide.properties.get(openslide.PROPERTY_NAME_OBJECTIVE_POWER)
        if op is not None:
            out["objective_power"] = float(op)
    except Exception:
        pass
    try:
        out["level_count"] = int(slide.level_count)
    except Exception:
        pass
    try:
        out["level_downsamples"] = [float(d) for d in slide.level_downsamples]
    except Exception:
        pass
    try:
        out["level_dimensions"] = [(int(w), int(h)) for w, h in slide.level_dimensions]
    except Exception:
        pass
    return out


def generate_wsi_thumbnail(path: Path, max_dim: int = 1024) -> ThumbResult:
    slide = try_open_wsi(path)
    if slide is None:
        return generate_image_thumbnail(path, max_dim)

    try:
        orig_w, orig_h = slide.dimensions
        thumb = slide.get_thumbnail((max_dim, max_dim))
        rgb = thumb.convert("RGB")
        thumb_w, thumb_h = rgb.size
        with io.BytesIO() as buf:
            rgb.save(buf, format="PNG", optimize=True)
            png_bytes = buf.getvalue()
        meta = _extract_wsi_metadata(slide)
        return ThumbResult(
            png_bytes=png_bytes,
            orig_w=orig_w,
            orig_h=orig_h,
            thumb_w=thumb_w,
            thumb_h=thumb_h,
            is_wsi=True,
            **meta,
        )
    finally:
        slide.close()


def extract_wsi_metadata(path: Path) -> dict | None:
    """Re-extract metadata for an existing slide. Returns None if the file can't
    be opened as WSI. Used by lazy migration of legacy cases."""
    slide = try_open_wsi(path)
    if slide is None:
        return None
    try:
        return _extract_wsi_metadata(slide)
    finally:
        slide.close()


def generate_thumbnail(path: Path, max_dim: int = 1024) -> ThumbResult:
    return generate_wsi_thumbnail(path, max_dim)


# Re-export for UI layer convenience (Phase 2+).
from slide_stitcher.services.wsi_cache import WSIHandleCache  # noqa: E402

