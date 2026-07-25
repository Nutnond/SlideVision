from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, QThread, Signal

from slide_stitcher.config import settings
from slide_stitcher.models import CaseMetadata, Mapping, SlideMetadata, SlidePosition
from slide_stitcher.services import compose, mapping, storage, wsi


class MetadataExtractionWorker(QObject):
    """Re-extracts WSI metadata (mpp, objective-power, level info) for slides in
    a case that were registered before Phase 1 added these fields. Runs in a
    background QThread so opening a legacy case is not blocked."""

    progress = Signal(int, str)
    finished = Signal(object)  # CaseMetadata with updated slides
    failed = Signal(str)

    def __init__(self, case: CaseMetadata) -> None:
        super().__init__()
        self._case = case

    def run(self) -> None:
        try:
            slides = [s for s in self._case.slides if s.has_wsi and s.mpp_x is None]
            total = len(slides)
            for i, slide in enumerate(slides, 1):
                meta = wsi.extract_wsi_metadata(Path(slide.original_path))
                if meta is not None:
                    slide.mpp_x = meta["mpp_x"]
                    slide.mpp_y = meta["mpp_y"]
                    slide.objective_power = meta["objective_power"]
                    slide.level_count = meta["level_count"]
                    slide.level_downsamples = meta["level_downsamples"]
                    slide.level_dimensions = meta["level_dimensions"]
                self.progress.emit(int(100 * i / max(1, total)), f"Extracting metadata {i}/{total}")
            mapping.save_case(self._case)
            self.finished.emit(self._case)
        except Exception as e:
            self.failed.emit(str(e))


class CaseController(QObject):
    caseLoaded = Signal(object)
    caseClosed = Signal()
    slidesAdded = Signal(list)
    slidesUpdated = Signal(object)  # CaseMetadata after lazy metadata migration
    slideRemoved = Signal(str)
    mappingSaved = Signal()
    dirtyChanged = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._case: CaseMetadata | None = None
        self._mapping: Mapping | None = None
        self._dirty: bool = False
        self._meta_thread: QThread | None = None
        self._meta_worker: MetadataExtractionWorker | None = None

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
        self._maybe_start_metadata_migration(case)
        return case

    def close_case(self) -> None:
        self._stop_metadata_migration()
        self._case = None
        self._mapping = None
        self.clear_dirty()
        self.caseClosed.emit()

    def _maybe_start_metadata_migration(self, case: CaseMetadata) -> None:
        """Spawn background worker to extract WSI metadata for legacy slides that
        were registered before mpp/level fields existed. No-op if all slides are
        already migrated or none are WSI."""
        needs = [s for s in case.slides if s.has_wsi and s.mpp_x is None]
        if not needs:
            return
        self._stop_metadata_migration()
        self._meta_thread = QThread()
        self._meta_worker = MetadataExtractionWorker(case)
        self._meta_worker.moveToThread(self._meta_thread)
        self._meta_thread.started.connect(self._meta_worker.run)
        self._meta_worker.finished.connect(self._on_metadata_finished, Qt.QueuedConnection)
        self._meta_worker.failed.connect(self._on_metadata_failed, Qt.QueuedConnection)
        self._meta_worker.finished.connect(self._meta_thread.quit)
        self._meta_worker.failed.connect(self._meta_thread.quit)
        self._meta_thread.finished.connect(self._meta_worker.deleteLater)
        self._meta_thread.finished.connect(self._meta_thread.deleteLater)
        self._meta_thread.start()

    def _stop_metadata_migration(self) -> None:
        if self._meta_thread is not None:
            self._meta_thread.requestInterruption()
            self._meta_thread.quit()
            self._meta_thread.wait(3000)
            self._meta_thread = None
            self._meta_worker = None

    def _on_metadata_finished(self, case: CaseMetadata) -> None:
        self._meta_thread = None
        self._meta_worker = None
        self.slidesUpdated.emit(case)

    def _on_metadata_failed(self, err: str) -> None:
        print(f"[metadata migration] failed: {err}")
        self._meta_thread = None
        self._meta_worker = None

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
                mpp_x=result.mpp_x,
                mpp_y=result.mpp_y,
                objective_power=result.objective_power,
                level_count=result.level_count,
                level_downsamples=result.level_downsamples,
                level_dimensions=result.level_dimensions,
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
