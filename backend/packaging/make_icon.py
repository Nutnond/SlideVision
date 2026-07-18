"""Generate SlideVision app icon (.icns for Mac, .ico for Windows).
Run: pixi run python packaging/make_icon.py
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUTPUT_DIR = Path(__file__).parent / "icons"
ICONSET_DIR = OUTPUT_DIR / "icon.iconset"

# Brand gradient: indigo → violet
TOP_COLOR = (99, 102, 241)     # #6366f1 indigo-500
BOT_COLOR = (139, 92, 246)     # #8b5cf6 violet-500
ACCENT_COLOR = (236, 72, 153)  # #ec4899 pink-500


def make_gradient(size: int, top: tuple, bot: tuple) -> Image.Image:
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    for y in range(size):
        t = y / max(1, size - 1)
        arr[y, :, 0] = int(top[0] + (bot[0] - top[0]) * t)
        arr[y, :, 1] = int(top[1] + (bot[1] - top[1]) * t)
        arr[y, :, 2] = int(top[2] + (bot[2] - top[2]) * t)
        arr[y, :, 3] = 255
    return Image.fromarray(arr, "RGBA")


def make_icon(size: int) -> Image.Image:
    img = make_gradient(size, TOP_COLOR, BOT_COLOR)

    # Mask to rounded square (macOS 'apps' shape)
    margin = int(size * 0.04)
    radius = int(size * 0.22)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [margin, margin, size - margin, size - margin], radius=radius, fill=255
    )
    img.putalpha(mask)

    # Soft inner highlight (top glow)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.rounded_rectangle(
        [margin, margin, size - margin, int(size * 0.55)],
        radius=radius,
        fill=(255, 255, 255, 40),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size // 16))
    img = Image.alpha_composite(img, glow)

    # Draw 4 slide tiles in 2x2 grid (the "stitched" metaphor)
    draw = ImageDraw.Draw(img)
    grid_margin = int(size * 0.24)
    gap = int(size * 0.05)
    cell_size = (size - 2 * grid_margin - gap) // 2

    positions = [
        (grid_margin, grid_margin),
        (grid_margin + cell_size + gap, grid_margin),
        (grid_margin, grid_margin + cell_size + gap),
        (grid_margin + cell_size + gap, grid_margin + cell_size + gap),
    ]
    cell_radius = max(2, int(cell_size * 0.16))

    # Subtle shadow under cells
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    for px, py in positions:
        shadow_draw.rounded_rectangle(
            [px + size // 64, py + size // 64, px + cell_size + size // 64, py + cell_size + size // 64],
            radius=cell_radius,
            fill=(0, 0, 0, 70),
        )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=size // 80))
    img = Image.alpha_composite(img, shadow)

    # White tile cells
    draw = ImageDraw.Draw(img)
    for px, py in positions:
        draw.rounded_rectangle(
            [px, py, px + cell_size, py + cell_size],
            radius=cell_radius,
            fill=(255, 255, 255, 245),
        )

    # Pink accent dot in top-right cell (the "vision" eye)
    acc_x = positions[1][0] + cell_size // 2
    acc_y = positions[1][1] + cell_size // 2
    acc_r = max(2, int(cell_size * 0.18))
    draw.ellipse(
        [acc_x - acc_r, acc_y - acc_r, acc_x + acc_r, acc_y + acc_r],
        fill=ACCENT_COLOR + (255,),
    )

    return img


def build_iconset() -> None:
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    icons = {s: make_icon(s) for s in sizes}

    mapping = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for fname, sz in mapping.items():
        icons[sz].save(ICONSET_DIR / fname, "PNG")
    # Also save a square 1024 for use as a generic icon
    icons[1024].save(OUTPUT_DIR / "icon_1024.png", "PNG")
    icons[512].save(OUTPUT_DIR / "icon_512.png", "PNG")
    print(f"[icon] PNGs written to {ICONSET_DIR}")


def build_icns() -> Path:
    out = OUTPUT_DIR / "icon.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(out)],
        check=True,
    )
    print(f"[icon] .icns written to {out}")
    return out


def build_ico() -> Path:
    out = OUTPUT_DIR / "icon.ico"
    sizes = [16, 32, 48, 64, 128, 256]
    imgs = [make_icon(s) for s in sizes]
    imgs[0].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
    print(f"[icon] .ico written to {out}")
    return out


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    build_iconset()
    if sys.platform == "darwin":
        build_icns()
    build_ico()


if __name__ == "__main__":
    main()
