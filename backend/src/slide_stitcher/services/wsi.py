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
        return ThumbResult(
            png_bytes=png_bytes,
            orig_w=orig_w,
            orig_h=orig_h,
            thumb_w=thumb_w,
            thumb_h=thumb_h,
            is_wsi=True,
        )
    finally:
        slide.close()


def generate_thumbnail(path: Path, max_dim: int = 1024) -> ThumbResult:
    return generate_wsi_thumbnail(path, max_dim)
