import json
from pathlib import Path

from slide_stitcher.models import CaseMetadata, Mapping
from slide_stitcher.services import storage


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def load_case(case_id: str) -> CaseMetadata | None:
    data = _read_json(storage.case_meta_path(case_id), None)
    if data is None:
        return None
    return CaseMetadata(**data)


def save_case(case: CaseMetadata) -> None:
    storage.ensure_case_dir(case.id)
    _write_json(storage.case_meta_path(case.id), case.model_dump())


def load_mapping(case_id: str) -> Mapping:
    data = _read_json(storage.mapping_path(case_id), None)
    if data is None:
        return Mapping(case_id=case_id, slides=[])
    return Mapping(**data)


def save_mapping(mapping: Mapping) -> None:
    storage.ensure_case_dir(mapping.case_id)
    _write_json(storage.mapping_path(mapping.case_id), mapping.model_dump())
