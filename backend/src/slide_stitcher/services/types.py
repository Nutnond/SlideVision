from dataclasses import dataclass


@dataclass
class ThumbResult:
    png_bytes: bytes
    orig_w: int
    orig_h: int
    thumb_w: int
    thumb_h: int
    is_wsi: bool
