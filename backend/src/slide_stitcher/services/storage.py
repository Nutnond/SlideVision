from pathlib import Path

from slide_stitcher.config import settings


def ensure_dirs() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.cases_dir.mkdir(parents=True, exist_ok=True)


def case_dir(case_id: str) -> Path:
    return settings.cases_dir / case_id


def ensure_case_dir(case_id: str) -> Path:
    d = case_dir(case_id)
    (d / "slides").mkdir(parents=True, exist_ok=True)
    return d


def case_meta_path(case_id: str) -> Path:
    return case_dir(case_id) / "case.json"


def mapping_path(case_id: str) -> Path:
    return case_dir(case_id) / "mapping.json"


def composed_path(case_id: str) -> Path:
    return case_dir(case_id) / "composed.png"


def slide_dir(case_id: str, slide_id: str) -> Path:
    return case_dir(case_id) / "slides" / slide_id


def ensure_slide_dir(case_id: str, slide_id: str) -> Path:
    d = slide_dir(case_id, slide_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def original_path(case_id: str, slide_id: str, ext: str) -> Path:
    return slide_dir(case_id, slide_id) / f"original.{ext.lstrip('.')}"


def thumb_path(case_id: str, slide_id: str) -> Path:
    return slide_dir(case_id, slide_id) / "thumb.png"


def list_case_ids() -> list[str]:
    if not settings.cases_dir.exists():
        return []
    return sorted([d.name for d in settings.cases_dir.iterdir() if d.is_dir()])
