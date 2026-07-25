from datetime import datetime

from pydantic import BaseModel, Field


class SlideMetadata(BaseModel):
    id: str
    case_id: str
    filename: str
    original_filename: str
    original_path: str = ""
    width: int
    height: int
    thumb_width: int
    thumb_height: int
    has_wsi: bool = False
    # WSI magnification metadata (None when unknown / not yet extracted).
    # Used for microscope-style magnification display + deep-zoom level selection.
    mpp_x: float | None = None
    mpp_y: float | None = None
    objective_power: float | None = None
    level_count: int = 0
    level_downsamples: list[float] = []
    level_dimensions: list[tuple[int, int]] = []
    created_at: datetime = Field(default_factory=datetime.now)


class CaseMetadata(BaseModel):
    id: str
    name: str
    slides: list[SlideMetadata] = []
    created_at: datetime = Field(default_factory=datetime.now)


class SlidePosition(BaseModel):
    id: str
    x: float
    y: float
    w: float
    h: float
    rotation: float = 0.0
    crop_x: float = 0.0
    crop_y: float = 0.0
    crop_w: float = 1.0
    crop_h: float = 1.0
    # Cumulative applied crop in original normalized coords.
    # After "Apply Crop", these reflect what part of the original is now the slide.
    applied_x: float = 0.0
    applied_y: float = 0.0
    applied_w: float = 1.0
    applied_h: float = 1.0


class Mapping(BaseModel):
    case_id: str
    slides: list[SlidePosition] = []
