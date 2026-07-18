from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from slide_stitcher.models import CaseMetadata, SlideMetadata
from slide_stitcher.ui.controllers.case_controller import CaseController

SLIDE_FILTER = (
    "Pathology Slides (*.ndpi *.svs *.mrxs *.vms *.scn *.bif *.tif *.tiff "
    "*.jpg *.jpeg *.png *.bmp *.webp);;All Files (*.*)"
)


class CaseSidebar(QWidget):
    slideClicked = Signal(str)
    slideDoubleClicked = Signal(str)
    removeRequested = Signal(str)

    def __init__(self, controller: CaseController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Slides")
        title.setStyleSheet("font-weight: 600; color: #94a3b8; font-size: 12px; letter-spacing: 0.5px;")
        layout.addWidget(title)

        self.add_btn = QPushButton("+ Add Slides…")
        self.add_btn.clicked.connect(self._on_add_slides)
        layout.addWidget(self.add_btn)

        self.count_label = QLabel("0 slides")
        self.count_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.count_label)

        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setIconSize(QSize(140, 100))
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setSpacing(6)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, 1)

        self.empty_label = QLabel("No case loaded.\n\nFile → New Case to begin.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #64748b; padding: 30px; font-size: 12px;")
        layout.addWidget(self.empty_label)

        controller.caseLoaded.connect(self._on_case_loaded)
        controller.caseClosed.connect(self._on_case_closed)
        controller.slidesAdded.connect(self._on_slides_added)
        controller.slideRemoved.connect(self._on_slide_removed)

        self._set_has_case(False)

    def _set_has_case(self, has_case: bool) -> None:
        self.add_btn.setEnabled(has_case)
        self.list_widget.setVisible(has_case)
        self.count_label.setVisible(has_case)
        self.empty_label.setVisible(not has_case)

    def _on_case_loaded(self, case: CaseMetadata) -> None:
        self._set_has_case(True)
        self.list_widget.clear()
        for slide in case.slides:
            self._add_slide_item(slide)
        self._update_count()

    def _on_case_closed(self) -> None:
        self.list_widget.clear()
        self._set_has_case(False)

    def _on_slides_added(self, slides: list[SlideMetadata]) -> None:
        for slide in slides:
            self._add_slide_item(slide)
        self._update_count()

    def _on_slide_removed(self, slide_id: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == slide_id:
                self.list_widget.takeItem(i)
                break
        self._update_count()

    def _add_slide_item(self, slide: SlideMetadata) -> None:
        thumb = self.controller.thumb_path(slide.id)
        pixmap = QPixmap(str(thumb))
        badge = "WSI · " if slide.has_wsi else ""
        label = f"{slide.original_filename}\n{badge}{slide.width}×{slide.height}"
        item = QListWidgetItem(QIcon(pixmap), label)
        item.setData(Qt.UserRole, slide.id)
        item.setToolTip(f"{slide.original_filename}\n{slide.original_path}\n{slide.width}×{slide.height}")
        self.list_widget.addItem(item)

    def _update_count(self) -> None:
        n = self.list_widget.count()
        self.count_label.setText(f"{n} slide{'s' if n != 1 else ''}")

    def _on_add_slides(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select slide files", "", SLIDE_FILTER)
        if files:
            self.controller.register_slides([Path(f) for f in files])

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.slideClicked.emit(item.data(Qt.UserRole))

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self.slideDoubleClicked.emit(item.data(Qt.UserRole))

    def _selected_slide_ids(self) -> list[str]:
        return [item.data(Qt.UserRole) for item in self.list_widget.selectedItems()]

    def _on_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        act_add_canvas = menu.addAction("Add to canvas")
        menu.addSeparator()
        act_remove_canvas = menu.addAction("Remove from canvas")
        act_delete = menu.addAction("Delete from case…")
        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen is None:
            return
        slide_id = item.data(Qt.UserRole)
        if chosen == act_add_canvas:
            self.slideClicked.emit(slide_id)
        elif chosen == act_remove_canvas:
            self.removeRequested.emit(slide_id)
        elif chosen == act_delete:
            self._confirm_delete(self._selected_slide_ids() or [slide_id])

    def _confirm_delete(self, slide_ids: list[str]) -> None:
        if not slide_ids:
            return
        n = len(slide_ids)
        reply = QMessageBox.question(
            self,
            "Delete slide(s)",
            f"Permanently delete {n} slide(s) from the case?\n"
            "(The original file on disk is not touched.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for sid in slide_ids:
            self.controller.remove_slide(sid)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete and self.list_widget.selectedItems():
            self._confirm_delete(self._selected_slide_ids())
            event.accept()
            return
        super().keyPressEvent(event)
