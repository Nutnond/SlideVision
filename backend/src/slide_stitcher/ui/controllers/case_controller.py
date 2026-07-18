from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from slide_stitcher.config import settings
from slide_stitcher.models import CaseMetadata, Mapping, SlideMetadata, SlidePosition
from slide_stitcher.services import compose, mapping, storage, wsi


class CaseController(QObject):
    caseLoaded = Signal(object)
    caseClosed = Signal()
    slidesAdded = Signal(list)
    slideRemoved = Signal(str)
    mappingSaved = Signal()
    dirtyChanged = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._case: CaseMetadata | None = None
        self._mapping: Mapping | None = None
        self._dirty: bool = False

    @property
    def case(self) -> CaseMetadata | None:
        return self._case

    @property
    def mapping(self) -> Mapping | None:
        return self._mapping

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self.dirtyChanged.emit(True)

    def clear_dirty(self) -> None:
        if self._dirty:
            self._dirty = False
            self.dirtyChanged.emit(False)

    def new_case(self, name: str) -> CaseMetadata:
        case = CaseMetadata(id=uuid4().hex, name=name or self._default_name())
        storage.ensure_case_dir(case.id)
        mapping.save_case(case)
        self._case = case
        self._mapping = Mapping(case_id=case.id, slides=[])
        self.clear_dirty()
        self.caseLoaded.emit(case)
        return case

    def open_case(self, case_id: str) -> CaseMetadata | None:
        case = mapping.load_case(case_id)
        if case is None:
            return None
        self._case = case
        self._mapping = mapping.load_mapping(case_id)
        self.clear_dirty()
        self.caseLoaded.emit(case)
        return case

    def close_case(self) -> None:
        self._case = None
        self._mapping = None
        self.clear_dirty()
        self.caseClosed.emit()

    def delete_case(self, case_id: str) -> None:
        """Permanently delete an entire case (metadata + slides + thumbnails)."""
        import shutil
        d = storage.case_dir(case_id)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        if self._case is not None and self._case.id == case_id:
            self.close_case()

    def list_cases(self) -> list[CaseMetadata]:
        out: list[CaseMetadata] = []
        for case_id in storage.list_case_ids():
            c = mapping.load_case(case_id)
            if c is not None:
                out.append(c)
        return out

    def register_slides(self, paths: list[Path]) -> list[SlideMetadata]:
        if self._case is None:
            raise RuntimeError("No case loaded")
        new_slides: list[SlideMetadata] = []
        for path in paths:
            try:
                result = wsi.generate_thumbnail(path, settings.thumb_max_dim)
            except Exception as e:
                print(f"[register_slides] Failed {path}: {e}")
                continue
            slide_id = uuid4().hex
            storage.ensure_slide_dir(self._case.id, slide_id)
            storage.thumb_path(self._case.id, slide_id).write_bytes(result.png_bytes)
            meta = SlideMetadata(
                id=slide_id,
                case_id=self._case.id,
                filename=str(path),
                original_filename=path.name,
                original_path=str(path),
                width=result.orig_w,
                height=result.orig_h,
                thumb_width=result.thumb_w,
                thumb_height=result.thumb_h,
                has_wsi=result.is_wsi,
            )
            self._case.slides.append(meta)
            new_slides.append(meta)
        if new_slides:
            mapping.save_case(self._case)
            self.slidesAdded.emit(new_slides)
        return new_slides

    def remove_slide(self, slide_id: str) -> None:
        if self._case is None:
            return
        self._case.slides = [s for s in self._case.slides if s.id != slide_id]
        mapping.save_case(self._case)
        if self._mapping and any(p.id == slide_id for p in self._mapping.slides):
            self._mapping.slides = [p for p in self._mapping.slides if p.id != slide_id]
            mapping.save_mapping(self._mapping)
        import shutil
        sd = storage.slide_dir(self._case.id, slide_id)
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        self.slideRemoved.emit(slide_id)

    def thumb_path(self, slide_id: str) -> Path:
        if self._case is None:
            raise RuntimeError("No case loaded")
        return storage.thumb_path(self._case.id, slide_id)

    def save_mapping(self, positions: list[SlidePosition]) -> None:
        if self._case is None:
            return
        m = Mapping(case_id=self._case.id, slides=positions)
        mapping.save_mapping(m)
        self._mapping = m
        self.clear_dirty()
        self.mappingSaved.emit()

    def export(self, positions: list[SlidePosition], output_path: Path, scale: float = 1.0) -> tuple[int, int]:
        if self._case is None:
            raise RuntimeError("No case loaded")
        m = Mapping(case_id=self._case.id, slides=positions)
        png_bytes, w, h = compose.compose_image(self._case, m, scale=scale)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(png_bytes)
        return w, h

    def export_full_res(self, positions: list[SlidePosition], output_path: Path) -> tuple[int, int]:
        if self._case is None:
            raise RuntimeError("No case loaded")
        m = Mapping(case_id=self._case.id, slides=positions)
        png_bytes, w, h = compose.compose_image_full_res(self._case, m)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(png_bytes)
        return w, h

    @staticmethod
    def _default_name() -> str:
        return f"Case {datetime.now().strftime('%Y-%m-%d %H:%M')}"
