from pathlib import Path

from PySide6.QtCore import QObject, Qt, QRectF, QThread, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QWidget,
)

from slide_stitcher.models import CaseMetadata, Mapping, SlideMetadata
from slide_stitcher.services import compose
from slide_stitcher.services.tile_reader import TileRequest, pick_level_for_downsample
from slide_stitcher.services.wsi_cache import WSIHandleCache
from slide_stitcher.services import arrange
from slide_stitcher.ui.controllers.case_controller import CaseController
from slide_stitcher.ui.dialogs.arrange_dialog import ArrangeDialog
from slide_stitcher.ui.dialogs.crop_dialog import CropDialog
from slide_stitcher.ui.dialogs.new_case_dialog import NewCaseDialog
from slide_stitcher.ui.tile_loader import TileLoader
from slide_stitcher.ui.widgets.case_sidebar import CaseSidebar
from slide_stitcher.ui.widgets.slide_canvas import SlideCanvas, ZOOM_LABELS, ZOOM_STOPS
from slide_stitcher.ui.widgets.welcome_screen import WelcomeScreen


class FullResExportWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(int, int)
    failed = Signal(str)
    output_ready = Signal(object)

    def __init__(self, controller, positions: list, output_path: Path) -> None:
        super().__init__()
        self._controller = controller
        self._positions = positions
        self._output_path = output_path

    def run(self) -> None:
        try:
            case = self._controller.case
            if case is None:
                self.failed.emit("No case loaded")
                return
            mapping = Mapping(case_id=case.id, slides=self._positions)
            png_bytes, w, h = compose.compose_image_full_res(
                case,
                mapping,
                progress_cb=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            self._output_path.write_bytes(png_bytes)
            self.output_ready.emit(png_bytes)
            self.finished.emit(w, h)
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SlideVision")
        self.resize(1400, 900)
        self._restore_geometry()

        self.controller = CaseController()
        self.controller.caseLoaded.connect(self._on_case_loaded)
        self.controller.dirtyChanged.connect(self._on_dirty_changed)

        # Deep-zoom infrastructure (Phase 3). Owned by MainWindow; cache is
        # closed on case-close and on app exit.
        self._wsi_cache = WSIHandleCache()
        self._tile_loader = TileLoader(self._wsi_cache, parent=self)
        self._tile_loader.tileReady.connect(self._on_tile_ready, Qt.QueuedConnection)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._build_statusbar()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Stacked: welcome screen (when no case) ↔ workspace (sidebar + canvas)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)

        self.sidebar = CaseSidebar(self.controller)
        self.sidebar.slideClicked.connect(self._on_slide_clicked)
        self.sidebar.removeRequested.connect(self._on_sidebar_remove_requested)

        self.canvas = SlideCanvas()
        self.canvas.slideMoved.connect(self._on_canvas_slide_moved)
        self.canvas.slideResized.connect(self._on_canvas_slide_resized)
        self.canvas.slideRotated.connect(self._on_canvas_slide_rotated)
        self.canvas.slideCropped.connect(self._on_canvas_slide_cropped)
        self.canvas.selectionChanged.connect(self._on_canvas_selection)

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.canvas)
        self.splitter.setSizes([300, 1100])

        self.welcome = WelcomeScreen(self.controller)
        self.welcome.newCaseRequested.connect(self._on_new_case)
        self.welcome.openCaseRequested.connect(self._open_recent)
        self.welcome.browseCaseRequested.connect(self._on_open_case)

        layout.addWidget(self.welcome)
        layout.addWidget(self.splitter)
        self.splitter.hide()

        self.setCentralWidget(central)
        self._show_welcome()

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        menubar.setNativeMenuBar(False)

        file_menu = menubar.addMenu("&File")
        file_menu.addAction("&New Case…", self._on_new_case, "Ctrl+N")
        file_menu.addAction("&Open Case…", self._on_open_case, "Ctrl+O")
        self.recent_menu = file_menu.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._refresh_recent)
        file_menu.addSeparator()
        file_menu.addAction("&Save Mapping", self._on_save, "Ctrl+S")
        file_menu.addAction("&Export PNG…", self._on_export, "Ctrl+E")
        file_menu.addAction("Export &Full-Quality PNG…", self._on_export_full_res, "Ctrl+Shift+E")
        file_menu.addSeparator()
        file_menu.addAction("&Delete Current Case…", self._on_delete_current_case)
        file_menu.addSeparator()
        file_menu.addAction("&Home (close case)", self._on_home, "Ctrl+Shift+W")
        file_menu.addAction("E&xit", self.close, "Ctrl+Q")

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction("&Remove from canvas", self._on_remove_selected, "Delete")
        edit_menu.addAction("&Crop Selected… (numeric)", self._on_crop_selected, "Ctrl+K")
        edit_menu.addAction("&Apply Crop (commit)", self._on_apply_crop, "Return")
        edit_menu.addAction("&Reset pending crop (selected)", self._on_reset_crop, "Ctrl+Shift+K")
        edit_menu.addAction("Reset &Rotation (selected)", self._on_reset_rotation, "Ctrl+R")
        edit_menu.addAction("Delete slide entirely…", self._on_delete_slide_entirely, "Shift+Delete")
        edit_menu.addSeparator()
        edit_menu.addAction("&Auto-Arrange Slides…", self._on_auto_arrange, "Ctrl+Shift+A")
        self.magnetic_action = edit_menu.addAction("&Magnetic Edges")
        self.magnetic_action.setCheckable(True)
        self.magnetic_action.setChecked(True)
        self.magnetic_action.setShortcut("Ctrl+Shift+M")
        self.magnetic_action.toggled.connect(self._on_toggle_magnetic)

        view_menu = menubar.addMenu("&View")
        view_menu.addAction("&Fit to View", self._on_fit_view, "Ctrl+0")
        view_menu.addAction("Zoom &In (next stop)", self._on_zoom_in, "Ctrl++")
        view_menu.addAction("Zoom &Out (prev stop)", self._on_zoom_out, "Ctrl+-")

        zoom_menu: QMenu = view_menu.addMenu("&Canvas Zoom")
        zoom_menu.setToolTip(
            "Sets canvas zoom factor. Effective microscope power depends on each "
            "slide's native resolution and is shown in the status bar."
        )
        for i, label in enumerate(ZOOM_LABELS):
            action = zoom_menu.addAction(label, lambda checked=False, idx=i: self.canvas.set_zoom_index(idx))
            action.setToolTip(f"Canvas zoom = {ZOOM_STOPS[i]:.0f}× (not microscope magnification)")
            action.setShortcutContext(Qt.ApplicationShortcut)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("&About SlideVision", self._on_about)

    def _build_shortcuts(self) -> None:
        for keys in (
            QKeySequence.StandardKey.Delete,
            QKeySequence(Qt.Key_Delete),
            QKeySequence(Qt.Key_Backspace),
        ):
            sc = QShortcut(keys, self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._on_remove_selected)

        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.ApplicationShortcut)
        esc.activated.connect(self._clear_selection)

        # Magnification stops — number keys 1..N jump to that stop.
        for i in range(len(ZOOM_STOPS)):
            sc = QShortcut(QKeySequence(str(i + 1)), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(lambda checked=False, idx=i: self.canvas.set_zoom_index(idx))

    def _build_statusbar(self) -> None:
        self.canvas_zoom_label = QLabel("Canvas: 1×")
        self.canvas_zoom_label.setStyleSheet("padding: 0 12px; color: #94a3b8;")
        self.effective_label = QLabel("")
        self.effective_label.setStyleSheet(
            "padding: 0 12px; color: #fbbf24; font-weight: 600;"
        )
        self.statusBar().addPermanentWidget(self.canvas_zoom_label)
        self.statusBar().addPermanentWidget(self.effective_label)
        self.statusBar().showMessage("Ready")

        # Wire canvas signals (defined after _build_ui; safe to do here too).
        self.canvas.zoomChanged.connect(self._on_zoom_changed, Qt.QueuedConnection)
        self.canvas.cursorSlideChanged.connect(self._on_cursor_slide_changed, Qt.QueuedConnection)
        self.canvas.viewportChanged.connect(self._on_viewport_changed, Qt.QueuedConnection)

    def _on_case_loaded(self, case: CaseMetadata) -> None:
        self.setWindowTitle(f"SlideVision — {case.name}")
        # Drop cached handles + tiles from any previously open case.
        self._wsi_cache.close_all()
        from PySide6.QtGui import QPixmapCache
        QPixmapCache.clear()
        self.canvas.clear_slides()
        for slide in case.slides:
            self._load_slide_to_canvas(slide)
        mapping = self.controller.mapping
        if mapping is not None and mapping.slides:
            self.canvas.load_positions(mapping.slides)
        self._show_workspace()
        n = len(case.slides)
        self.statusBar().showMessage(f"Case: {case.name} · {n} slide(s)")
        # Reset status bar magnification readouts.
        self.canvas_zoom_label.setText(f"Canvas: {self.canvas.current_zoom_label()}")
        self.effective_label.setText("")

    def _show_welcome(self) -> None:
        self.welcome.show()
        self.welcome._refresh()
        self.splitter.hide()
        self.statusBar().showMessage("Ready")

    def _show_workspace(self) -> None:
        self.welcome.hide()
        self.splitter.show()

    def _on_home(self) -> None:
        if not self._confirm_discard_dirty():
            return
        self.controller.close_case()
        self.setWindowTitle("SlideVision")
        self._show_welcome()

    def _on_delete_current_case(self) -> None:
        if self.controller.case is None:
            QMessageBox.information(self, "Delete Case", "No case loaded.")
            return
        case_id = self.controller.case.id
        name = self.controller.case.name
        reply = QMessageBox.question(
            self,
            "Delete Case",
            f"Permanently delete case '{name}'?\n\n"
            "All slide metadata and thumbnails will be removed.\n"
            "Original WSI files on disk are NOT touched.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.controller.delete_case(case_id)
        self.setWindowTitle("SlideVision")
        self._show_welcome()
        self.statusBar().showMessage(f"Deleted case '{name}'", 3000)

    def _load_slide_to_canvas(self, slide: SlideMetadata) -> None:
        pixmap = QPixmap(str(self.controller.thumb_path(slide.id)))
        if pixmap.isNull():
            print(f"Failed to load thumb for {slide.id}")
            return
        self.canvas.add_slide(slide, pixmap)

    def _on_dirty_changed(self, dirty: bool) -> None:
        case = self.controller.case
        if case is None:
            return
        prefix = "● " if dirty else ""
        self.setWindowTitle(f"{prefix}SlideVision — {case.name}")

    def _on_slide_clicked(self, slide_id: str) -> None:
        if self.controller.case is None:
            return
        slide = next((s for s in self.controller.case.slides if s.id == slide_id), None)
        if slide is None:
            return
        if not self.canvas.has_slide(slide_id):
            pixmap = QPixmap(str(self.controller.thumb_path(slide_id)))
            if not pixmap.isNull():
                self.canvas.add_slide(slide, pixmap)
        self.controller.mark_dirty()

    def _on_sidebar_remove_requested(self, slide_id: str) -> None:
        # Remove from canvas only (keep in case)
        if self.canvas.has_slide(slide_id):
            self.canvas.remove_slide(slide_id)
            self.controller.mark_dirty()
            self.statusBar().showMessage("Removed from canvas", 2000)

    def _on_canvas_slide_moved(self, _slide_id: str, _x: float, _y: float) -> None:
        self.controller.mark_dirty()

    def _on_canvas_slide_resized(self, _slide_id: str, _x, _y, _w, _h) -> None:
        self.controller.mark_dirty()

    def _on_canvas_slide_rotated(self, _slide_id: str, _degrees: float) -> None:
        self.controller.mark_dirty()

    def _on_canvas_slide_cropped(self, _slide_id: str) -> None:
        self.controller.mark_dirty()

    def _on_canvas_selection(self, ids: list[str]) -> None:
        n = len(ids)
        if n:
            self.statusBar().showMessage(f"{n} slide(s) selected")

    def _on_new_case(self) -> None:
        if not self._confirm_discard_dirty():
            return
        dialog = NewCaseDialog(self)
        if dialog.exec() == NewCaseDialog.Accepted:
            self.controller.new_case(dialog.name())

    def _on_open_case(self) -> None:
        if not self._confirm_discard_dirty():
            return
        cases = self.controller.list_cases()
        if not cases:
            QMessageBox.information(self, "Open Case", "No cases found in storage.")
            return
        items = [f"{c.name}  ({len(c.slides)} slides)" for c in cases]
        choice, ok = QInputDialog.getItem(
            self, "Open Case", "Select case:", items, 0, False
        )
        if ok:
            idx = items.index(choice)
            self.controller.open_case(cases[idx].id)

    def _refresh_recent(self) -> None:
        self.recent_menu.clear()
        cases = self.controller.list_cases()[:10]
        if not cases:
            act = self.recent_menu.addAction("(none)")
            act.setEnabled(False)
            return
        for c in cases:
            label = f"{c.name}  ({len(c.slides)} slides)"
            action = self.recent_menu.addAction(label)
            action.triggered.connect(lambda checked=False, cid=c.id: self._open_recent(cid))

    def _open_recent(self, case_id: str) -> None:
        if not self._confirm_discard_dirty():
            return
        self.controller.open_case(case_id)

    def _on_save(self) -> None:
        if self.controller.case is None:
            QMessageBox.information(self, "Save", "No case loaded.")
            return
        positions = self.canvas.get_positions()
        self.controller.save_mapping(positions)
        self.statusBar().showMessage(f"Saved {len(positions)} positions", 3000)

    def _on_export(self) -> None:
        if self.controller.case is None:
            QMessageBox.information(self, "Export", "No case loaded.")
            return
        positions = self.canvas.get_positions()
        if not positions:
            QMessageBox.information(self, "Export", "Place at least one slide on the canvas first.")
            return
        suggested = f"{self.controller.case.name}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Composed PNG", suggested, "PNG Image (*.png)"
        )
        if not path:
            return
        try:
            w, h = self.controller.export(positions, Path(path))
            QMessageBox.information(
                self, "Export Complete", f"Saved {w}×{h} PNG to:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def _on_export_full_res(self) -> None:
        if self.controller.case is None:
            QMessageBox.information(self, "Export", "No case loaded.")
            return
        positions = self.canvas.get_positions()
        if not positions:
            QMessageBox.information(self, "Export", "Place at least one slide on the canvas first.")
            return
        suggested = f"{self.controller.case.name}_fullres.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Full-Quality PNG", suggested, "PNG Image (*.png)"
        )
        if not path:
            return

        # Run export in background thread with progress dialog
        self._fullres_thread = QThread(self)
        self._fullres_worker = FullResExportWorker(self.controller, positions, Path(path))
        self._fullres_worker.moveToThread(self._fullres_thread)
        self._fullres_thread.started.connect(self._fullres_worker.run)

        self._progress = QProgressDialog("Preparing…", "Cancel", 0, 100, self)
        self._progress.setWindowTitle("Export Full-Quality PNG")
        self._progress.setMinimumWidth(420)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)
        self._progress.canceled.connect(self._fullres_thread.requestInterruption)

        self._fullres_worker.progress.connect(self._on_export_progress, Qt.QueuedConnection)
        self._fullres_worker.finished.connect(self._on_fullres_finished, Qt.QueuedConnection)
        self._fullres_worker.failed.connect(self._on_fullres_failed, Qt.QueuedConnection)
        # Cleanup connections
        self._fullres_worker.finished.connect(self._fullres_thread.quit)
        self._fullres_worker.failed.connect(self._fullres_thread.quit)
        self._fullres_thread.finished.connect(self._fullres_worker.deleteLater)
        self._fullres_thread.finished.connect(self._fullres_thread.deleteLater)

        self._export_path = path
        self._fullres_thread.start()

    def _on_fullres_finished(self, w: int, h: int) -> None:
        self._progress.hide()
        QMessageBox.information(
            self, "Export Complete",
            f"Saved full-resolution {w}×{h} PNG to:\n{self._export_path}\n\n"
            f"(Each slide rendered at its native WSI resolution.)"
        )
        self.statusBar().showMessage(f"Exported full-resolution PNG ({w}×{h})", 4000)

    def _on_fullres_failed(self, err: str) -> None:
        self._progress.hide()
        QMessageBox.critical(self, "Export Failed", err)

    def _on_export_progress(self, pct: int, msg: str) -> None:
        if hasattr(self, "_progress") and self._progress is not None:
            self._progress.setLabelText(msg)
            self._progress.setValue(pct)

    def _on_crop_selected(self) -> None:
        item = self.canvas.get_selected_item()
        if item is None:
            QMessageBox.information(self, "Crop", "Select a slide on the canvas first.")
            return
        initial = item.get_crop()
        dialog = CropDialog(initial, self)
        dialog.on_apply(lambda crop: item.set_crop(*crop))
        if dialog.exec() == CropDialog.Accepted:
            item.set_crop(*dialog.value())
            self.controller.mark_dirty()
        else:
            item.set_crop(*initial)

    def _on_reset_rotation(self) -> None:
        item = self.canvas.get_selected_item()
        if item is None:
            QMessageBox.information(self, "Reset Rotation", "Select a slide on the canvas first.")
            return
        item.set_rotation(0.0)
        self.controller.mark_dirty()

    def _on_reset_crop(self) -> None:
        item = self.canvas.get_selected_item()
        if item is None:
            QMessageBox.information(self, "Reset Crop", "Select a slide on the canvas first.")
            return
        item.set_crop(0.0, 0.0, 1.0, 1.0)
        self.controller.mark_dirty()
        self.statusBar().showMessage("Pending crop reset (does not undo applied crops)", 2500)

    def _on_apply_crop(self) -> None:
        result = self.canvas.apply_crop_selected()
        if result is None:
            self.statusBar().showMessage("Adjust crop first (drag orange edge handles)", 2500)
            return
        slide_id, _delta = result
        if self.controller.case is None:
            return
        meta = next((s for s in self.controller.case.slides if s.id == slide_id), None)
        if meta is None:
            return
        # Update the thumbnail on disk to the newly cropped pixmap
        item = self.canvas._items_by_id.get(slide_id)
        if item is not None:
            thumb_path = self.controller.thumb_path(slide_id)
            item.pixmap.save(str(thumb_path), "PNG")
        self.controller.mark_dirty()
        self.statusBar().showMessage(f"Crop applied to {meta.original_filename}", 2500)

    def _on_remove_selected(self) -> None:
        removed = self.canvas.remove_selected()
        if removed:
            self.controller.mark_dirty()
            self.statusBar().showMessage(f"Removed {len(removed)} from canvas", 2000)
        else:
            self.statusBar().showMessage("Nothing selected — click a slide first", 2000)

    def _clear_selection(self) -> None:
        self.canvas.scene.clearSelection()

    def _on_delete_slide_entirely(self) -> None:
        ids = self.canvas.get_selected_ids()
        if not ids:
            QMessageBox.information(self, "Delete Slide", "Select a slide on the canvas first.")
            return
        reply = QMessageBox.question(
            self,
            "Delete slide(s)",
            f"Permanently delete {len(ids)} slide(s) from the case? "
            "(The original file on disk is not touched.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for sid in ids:
            self.controller.remove_slide(sid)

    def _on_fit_view(self) -> None:
        self.canvas.fit_all()

    def _on_zoom_in(self) -> None:
        self.canvas.zoom_in()

    def _on_zoom_out(self) -> None:
        self.canvas.zoom_out()

    # --- Phase 3: magnification + deep-zoom handlers ---

    def _on_zoom_changed(self, idx: int, label: str) -> None:
        self.canvas_zoom_label.setText(f"Canvas: {label}")
        self._update_effective_label()
        self._schedule_tile_reload()

    def _on_cursor_slide_changed(self, slide_id: object) -> None:
        self._update_effective_label(slide_id if isinstance(slide_id, str) else None)
        self._schedule_tile_reload()

    def _on_viewport_changed(self) -> None:
        self._schedule_tile_reload()

    def _update_effective_label(self, slide_id: str | None = None) -> None:
        if slide_id is None:
            slide_id = self.canvas._cursor_slide_id
        if not slide_id or self.controller.case is None:
            self.effective_label.setText("")
            return
        meta = next((s for s in self.controller.case.slides if s.id == slide_id), None)
        if meta is None or not meta.has_wsi:
            self.effective_label.setText("")
            return
        power = self._compute_effective_power(meta)
        if power:
            text = f"Mag: {power}  ({meta.original_filename})"
        else:
            text = meta.original_filename
        self.effective_label.setText(text)

    def _compute_effective_power(self, meta: SlideMetadata) -> str:
        """Compute effective microscope power for the slide under cursor.
        Formula: native_objective × (displayed screen pixels / native pixels in view).
        Uses 1× ≈ 10µm/pixel convention when objective_power is missing."""
        item = self.canvas._items_by_id.get(meta.id)
        if item is None or meta.width == 0:
            return ""
        applied_w = item.get_applied_crop()[2]
        native_px_w = max(1.0, applied_w * meta.width)
        canvas_zoom = self.canvas.current_zoom_factor()
        displayed_px = item._w * canvas_zoom
        ratio = displayed_px / native_px_w  # >1 means upscaled past native detail
        if meta.objective_power:
            native = float(meta.objective_power)
        elif meta.mpp_x:
            native = 10.0 / float(meta.mpp_x)
        else:
            return "Unknown"
        effective = native * ratio
        if effective >= 10:
            return f"{effective:.0f}×"
        return f"{effective:.1f}×"

    def _schedule_tile_reload(self) -> None:
        """Recompute tile requests for all visible slides. Called on zoom,
        pan, scroll, resize, and cursor-slide change."""
        if self.controller.case is None:
            return
        canvas_zoom = self.canvas.current_zoom_factor()
        viewport = self.canvas.viewport().rect()
        visible_scene = self.canvas.mapToScene(viewport).boundingRect()
        active_slide_ids: set[str] = set()

        for slide_id, item in self.canvas._items_by_id.items():
            meta = next((s for s in self.controller.case.slides if s.id == slide_id), None)
            if meta is None or not meta.has_wsi or meta.width == 0 or meta.height == 0:
                item.set_tile_overlay_enabled(False)
                continue
            # Fallback: if metadata hasn't been migrated yet, treat as single-level WSI.
            downsamples = meta.level_downsamples or [1.0]

            # Density check — enable tiles when zoomed past thumbnail resolution.
            # Threshold 1.0 (was 1.5) so smaller-on-canvas slides still benefit.
            ratio = (canvas_zoom * item._w) / max(1, item.pixmap.width())
            if ratio < 1.0:
                item.set_tile_overlay_enabled(False)
                continue

            item_scene_rect = item.sceneBoundingRect()
            if not visible_scene.intersects(item_scene_rect):
                # Off-screen: clear overlay to save memory, but don't cancel (might come back)
                item.set_tile_overlay_enabled(False)
                continue

            active_slide_ids.add(slide_id)
            self._request_tiles_for(meta, item, canvas_zoom, visible_scene, downsamples)

        # Cancel pending requests for slides no longer active.
        for sid in list(self._tile_loader_keys()):
            if sid not in active_slide_ids:
                self._tile_loader.cancel(sid)

    def _request_tiles_for(self, meta: SlideMetadata, item, canvas_zoom: float, visible_scene, downsamples: list[float]) -> None:
        applied_x, applied_y, applied_w, applied_h = item.get_applied_crop()
        native_w = applied_w * meta.width
        native_h = applied_h * meta.height
        native_offset_x = applied_x * meta.width
        native_offset_y = applied_y * meta.height

        # Pick pyramid level: we want the level whose downsample gives ~1:1 with screen.
        desired_ds = native_w / max(1.0, item._w * canvas_zoom)
        level = pick_level_for_downsample(downsamples, desired_ds)
        actual_ds = downsamples[level] if level < len(downsamples) else 1.0

        tile_screen_size = 256  # at the chosen level
        tile_native = max(1, int(tile_screen_size * actual_ds))

        # Map viewport-visible scene rect into item-local coords (where 0,0 is the
        # pixmap's top-left, NOT the bounding-rect top-left which includes the
        # rotate-handle and corner-handle offsets). Handles rotation correctly
        # because mapFromScene accounts for the full scene transform.
        visible_local = item.mapFromScene(visible_scene).boundingRect().intersected(
            QRectF(0, 0, item._w, item._h)
        )
        if visible_local.isEmpty():
            item.set_tile_overlay_enabled(False)
            return
        # Map slide-local (0.._w) → native offset within the applied crop
        sx = native_w / max(1.0, item._w)
        sy = native_h / max(1.0, item._h)
        vis_x0 = max(0.0, visible_local.left()) * sx
        vis_y0 = max(0.0, visible_local.top()) * sy
        vis_x1 = min(native_w, max(0.0, visible_local.right()) * sx)
        vis_y1 = min(native_h, max(0.0, visible_local.bottom()) * sy)

        col0 = max(0, int(vis_x0 // tile_native))
        col1 = int(vis_x1 // tile_native)
        row0 = max(0, int(vis_y0 // tile_native))
        row1 = int(vis_y1 // tile_native)
        # Cap to keep requests bounded. 256 tiles × ~256KB = 64MB per slide max —
        # reasonable given 512MB QPixmapCache. With 4 worker pool, fills in ~2-4s.
        max_tiles_per_slide = 256
        if (col1 - col0 + 1) * (row1 - row0 + 1) > max_tiles_per_slide:
            item.set_tile_overlay_enabled(False)
            return

        item.set_tile_config({
            "level": level,
            "pixel_w": int(native_w),
            "pixel_h": int(native_h),
            "tile_size": tile_native,
            "applied_offset_x": int(native_offset_x),
            "applied_offset_y": int(native_offset_y),
        })
        item.set_tile_overlay_enabled(True)

        requests: list[TileRequest] = []
        for c in range(col0, col1 + 1):
            for r in range(row0, row1 + 1):
                ox = int(native_offset_x + c * tile_native)
                oy = int(native_offset_y + r * tile_native)
                requests.append(TileRequest(
                    slide_path=Path(meta.original_path),
                    region_origin=(ox, oy),
                    level=level,
                    region_size=(tile_screen_size, tile_screen_size),
                ))
        if requests:
            self._tile_loader.request(meta.id, requests)

    def _on_tile_ready(self, slide_id, level, ox, oy, sw, sh, pixmap) -> None:
        item = self.canvas._items_by_id.get(slide_id)
        if item is None or not item._tile_config:
            return
        if item._tile_config.get("level") != level:
            return  # tile belongs to an older request level
        item_local_ox = ox - item._tile_config.get("applied_offset_x", 0)
        item_local_oy = oy - item._tile_config.get("applied_offset_y", 0)
        item.set_tile_pixmap(item_local_ox, item_local_oy, pixmap)

    def _tile_loader_keys(self) -> set[str]:
        # The TileLoader doesn't expose its active keys; we approximate by
        # iterating all canvas slides. cancel() on a non-active id is a no-op.
        return set(self.canvas._items_by_id.keys())

    def _on_auto_arrange(self) -> None:
        if self.controller.case is None:
            QMessageBox.information(self, "Auto-Arrange", "No case loaded.")
            return
        positions = self.canvas.get_positions()
        if len(positions) < 2:
            QMessageBox.information(self, "Auto-Arrange", "Place at least 2 slides on the canvas first.")
            return

        dialog = ArrangeDialog(len(positions), self)
        if dialog.exec() != ArrangeDialog.Accepted:
            return
        params = dialog.params()

        if params["algorithm"] == ArrangeDialog.ALGO_GRID:
            new_positions = arrange.arrange_grid(
                positions,
                columns=params["columns"],
                gap=params["gap"],
                preserve_order=params["preserve_order"],
            )
        else:
            new_positions = arrange.arrange_row_pack(
                positions,
                target_row_height=params["target_row_height"],
                gap=params["gap"],
            )

        self.canvas.apply_positions(new_positions)
        self.controller.mark_dirty()
        self.statusBar().showMessage(f"Auto-arranged {len(new_positions)} slides", 3000)

    def _on_toggle_magnetic(self, enabled: bool) -> None:
        # Wire to canvas in Phase 4.
        if hasattr(self.canvas, "set_magnetic_enabled"):
            self.canvas.set_magnetic_enabled(enabled)
        self.statusBar().showMessage(
            f"Magnetic edges {'on' if enabled else 'off'}", 2000
        )

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About SlideVision",
            "<h3>SlideVision</h3>"
            "<p>Reconstruct pathology case overview from multiple slides.</p>"
            "<p>Version 0.3.0-dev · PySide6</p>"
            "<p><b>Shortcuts:</b><br>"
            "⌘N New · ⌘O Open · ⌘S Save · ⌘E Export<br>"
            "⌘0 Fit · ⌘+ Zoom in · ⌘- Zoom out<br>"
            "<b>1..6</b> Canvas zoom stops (1×/2×/4×/10×/20×/40×)<br>"
            "Delete Remove from canvas · Shift+⌫ Delete entirely</p>"
            "<p><b>Canvas zoom vs effective magnification:</b> The zoom buttons set a "
            "uniform canvas zoom factor. The <b>actual microscope power</b> depends on "
            "each slide's native scan resolution and is shown in the status bar "
            "(<i>Mag: NN× — filename</i>).</p>"
            "<p><i>Deep-zoom tiles load automatically when you zoom in past thumbnail resolution.</i></p>",
        )

    def _confirm_discard_dirty(self) -> bool:
        if not self.controller.dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            "You have unsaved changes. Discard and continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _restore_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            self.resize(min(1400, g.width() - 100), min(900, g.height() - 100))

    def closeEvent(self, event) -> None:
        if not self._confirm_discard_dirty():
            event.ignore()
            return
        # Shutdown background tile loader + release OpenSlide handles.
        try:
            self._tile_loader.shutdown()
            self._wsi_cache.close_all()
        except Exception as e:
            print(f"[shutdown] {e}")
        event.accept()
