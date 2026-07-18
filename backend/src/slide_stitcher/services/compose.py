import io
from pathlib import Path

import openslide
from PIL import Image

# Disable PIL's decompression-bomb safety check (intended for untrusted web images).
# Pathology WSI at native resolution easily exceeds the 178M-pixel default limit.
Image.MAX_IMAGE_PIXELS = None

from slide_stitcher.models import CaseMetadata, Mapping, SlidePosition
from slide_stitcher.services import storage

MAX_OUTPUT_DIM = 30000


def _apply_crop(img: Image.Image, pos: SlidePosition) -> Image.Image:
    if pos.crop_w >= 1.0 and pos.crop_h >= 1.0:
        return img
    cx = max(0.0, min(1.0, pos.crop_x))
    cy = max(0.0, min(1.0, pos.crop_y))
    cw = max(0.01, min(1.0 - cx, pos.crop_w))
    ch = max(0.01, min(1.0 - cy, pos.crop_h))
    box = (
        int(cx * img.width),
        int(cy * img.height),
        int((cx + cw) * img.width),
        int((cy + ch) * img.height),
    )
    return img.crop(box)


def _paste_position(pos: SlidePosition, img: Image.Image, min_x: float, min_y: float, scale: float) -> tuple[int, int]:
    if pos.rotation != 0:
        center_x = (pos.x - min_x + pos.w / 2) * scale
        center_y = (pos.y - min_y + pos.h / 2) * scale
        return int(center_x - img.width / 2), int(center_y - img.height / 2)
    return int((pos.x - min_x) * scale), int((pos.y - min_y) * scale)


def compose_image(
    case: CaseMetadata,
    mapping: Mapping,
    scale: float = 1.0,
    background: str = "white",
) -> tuple[bytes, int, int]:
    if not mapping.slides:
        raise ValueError("Mapping is empty — nothing to compose")

    slides_by_id = {s.id: s for s in case.slides}

    min_x = min(p.x for p in mapping.slides)
    min_y = min(p.y for p in mapping.slides)
    max_x = max(p.x + p.w for p in mapping.slides)
    max_y = max(p.y + p.h for p in mapping.slides)

    out_w = int((max_x - min_x) * scale)
    out_h = int((max_y - min_y) * scale)
    if out_w <= 0 or out_h <= 0:
        raise ValueError("Computed canvas size is non-positive")

    canvas = Image.new("RGB", (out_w, out_h), background)

    for pos in mapping.slides:
        meta = slides_by_id.get(pos.id)
        if meta is None:
            continue
        thumb_file = storage.thumb_path(case.id, pos.id)
        if not thumb_file.exists():
            continue
        with Image.open(thumb_file) as thumb:
            target_w = max(1, int(pos.w * scale))
            target_h = max(1, int(pos.h * scale))
            rgb = thumb.convert("RGB")
            rgb = _apply_crop(rgb, pos)
            resized = rgb.resize((target_w, target_h), Image.Resampling.LANCZOS)
            if pos.rotation != 0:
                resized = resized.rotate(-pos.rotation, expand=True)
            paste_x, paste_y = _paste_position(pos, resized, min_x, min_y, scale)
            canvas.paste(resized, (paste_x, paste_y))

    with io.BytesIO() as buf:
        canvas.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), out_w, out_h


def read_original_sized(path: Path, target_w: int, target_h: int, is_wsi: bool) -> Image.Image:
    if is_wsi:
        slide = openslide.open_slide(str(path))
        try:
            orig_w = slide.dimensions[0]
            downsample = max(1.0, orig_w / max(1, target_w))
            level = slide.get_best_level_for_downsample(downsample)
            level = max(0, min(level, slide.level_count - 1))
            lw, lh = slide.level_dimensions[level]
            img = slide.read_region((0, 0), level, (lw, lh)).convert("RGB")
        finally:
            slide.close()
    else:
        with Image.open(path) as src:
            img = src.convert("RGB")
    return img


def _apply_applied_crop(img: Image.Image, pos: SlidePosition) -> Image.Image:
    """Crop by cumulative applied region (in original normalized coords)."""
    if pos.applied_w >= 1.0 and pos.applied_h >= 1.0:
        return img
    ax = max(0.0, min(1.0, pos.applied_x))
    ay = max(0.0, min(1.0, pos.applied_y))
    aw = max(0.01, min(1.0 - ax, pos.applied_w))
    ah = max(0.01, min(1.0 - ay, pos.applied_h))
    box = (
        int(ax * img.width),
        int(ay * img.height),
        int((ax + aw) * img.width),
        int((ay + ah) * img.height),
    )
    return img.crop(box)


def compose_image_full_res(
    case: CaseMetadata,
    mapping: Mapping,
    background: str = "white",
    max_output_dim: int = MAX_OUTPUT_DIM,
    progress_cb=None,
) -> tuple[bytes, int, int]:
    if not mapping.slides:
        raise ValueError("Mapping is empty — nothing to compose")

    def _report(pct: int, msg: str) -> None:
        if progress_cb is not None:
            try:
                progress_cb(pct, msg)
            except Exception:
                pass

    _report(2, "Computing layout…")

    slides_by_id = {s.id: s for s in case.slides}

    global_scale = 1.0
    for pos in mapping.slides:
        meta = slides_by_id.get(pos.id)
        if meta and pos.w > 0 and meta.thumb_width > 0:
            s = meta.width / pos.w
            if s > global_scale:
                global_scale = s

    min_x = min(p.x for p in mapping.slides)
    min_y = min(p.y for p in mapping.slides)
    max_x = max(p.x + p.w for p in mapping.slides)
    max_y = max(p.y + p.h for p in mapping.slides)

    out_w = int((max_x - min_x) * global_scale)
    out_h = int((max_y - min_y) * global_scale)
    if out_w <= 0 or out_h <= 0:
        raise ValueError("Computed canvas size is non-positive")

    if max(out_w, out_h) > max_output_dim:
        ratio = max_output_dim / max(out_w, out_h)
        out_w = int(out_w * ratio)
        out_h = int(out_h * ratio)
        global_scale *= ratio

    _report(5, f"Allocating canvas {out_w}×{out_h}…")
    canvas = Image.new("RGB", (out_w, out_h), background)

    n = len(mapping.slides)
    for i, pos in enumerate(mapping.slides):
        meta = slides_by_id.get(pos.id)
        if meta is None or not meta.original_path:
            continue
        _report(5 + int(85 * i / max(1, n)), f"Reading slide {i+1}/{n}: {meta.original_filename}")
        target_w = max(1, int(pos.w * global_scale))
        target_h = max(1, int(pos.h * global_scale))
        try:
            img = read_original_sized(
                Path(meta.original_path), target_w, target_h, meta.has_wsi
            )
        except Exception as e:
            print(f"[compose_full_res] failed {meta.original_path}: {e}")
            continue
        img = _apply_applied_crop(img, pos)
        img = _apply_crop(img, pos)
        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        if pos.rotation != 0:
            img = img.rotate(-pos.rotation, expand=True)
        paste_x, paste_y = _paste_position(pos, img, min_x, min_y, global_scale)
        canvas.paste(img, (paste_x, paste_y))
        _report(5 + int(85 * (i + 1) / max(1, n)), f"Composited slide {i+1}/{n}")

    _report(92, "Encoding PNG…")
    with io.BytesIO() as buf:
        canvas.save(buf, format="PNG", optimize=False)
        _report(99, "Finalizing…")
        return buf.getvalue(), out_w, out_h

