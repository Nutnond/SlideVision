from dataclasses import dataclass, field


@dataclass
class ThumbResult:
    png_bytes: bytes
    orig_w: int
    orig_h: int
    thumb_w: int
    thumb_h: int
    is_wsi: bool
    # WSI magnification metadata. None / empty when source doesn't expose it.
    mpp_x: float | None = None
    mpp_y: float | None = None
    objective_power: float | None = None
    level_count: int = 0
    level_downsamples: list[float] = field(default_factory=list)
    level_dimensions: list[tuple[int, int]] = field(default_factory=list)
