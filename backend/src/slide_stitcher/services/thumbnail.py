import io
from pathlib import Path

from PIL import Image

from slide_stitcher.services.types import ThumbResult

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}


def generate_image_thumbnail(path: Path, max_dim: int = 1024) -> ThumbResult:
    with Image.open(path) as img:
        orig_w, orig_h = img.size
        rgb = img.convert("RGB")
        rgb.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
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
        is_wsi=False,
    )
