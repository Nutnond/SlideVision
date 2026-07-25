"""Arrange dialog — pick algorithm + parameters for auto-arrange."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QVBoxLayout,
)


class ArrangeDialog(QDialog):
    """Returns algorithm name + parameters via `.params()` dict on accept."""

    ALGO_GRID = "grid"
    ALGO_ROW_PACK = "row_pack"

    def __init__(self, slide_count: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Auto-Arrange Slides")
        self.setMinimumWidth(380)

        import math
        default_cols = max(1, int(math.ceil(math.sqrt(max(1, slide_count)))))

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.algo_combo = QComboBox()
        self.algo_combo.addItem("Grid (N columns)", self.ALGO_GRID)
        self.algo_combo.addItem("Row-pack (bin-pack by height)", self.ALGO_ROW_PACK)
        self.algo_combo.currentIndexChanged.connect(self._on_algo_changed)
        form.addRow("Algorithm:", self.algo_combo)

        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(1, 20)
        self.columns_spin.setValue(default_cols)
        form.addRow("Columns:", self.columns_spin)

        self.row_height_spin = QDoubleSpinBox()
        self.row_height_spin.setRange(50.0, 2000.0)
        self.row_height_spin.setSingleStep(50.0)
        self.row_height_spin.setSuffix(" px")
        self.row_height_spin.setValue(400.0)
        form.addRow("Target row height:", self.row_height_spin)

        self.gap_spin = QDoubleSpinBox()
        self.gap_spin.setRange(0.0, 200.0)
        self.gap_spin.setSingleStep(2.0)
        self.gap_spin.setSuffix(" px")
        self.gap_spin.setValue(8.0)
        form.addRow("Gap:", self.gap_spin)

        self.order_check = QCheckBox("Preserve sidebar order (uncheck for aspect-ratio balance)")
        self.order_check.setChecked(True)
        form.addRow(self.order_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_algo_changed(0)

    def _on_algo_changed(self, _idx: int) -> None:
        algo = self.algo_combo.currentData()
        is_grid = algo == self.ALGO_GRID
        self.columns_spin.setEnabled(is_grid)
        self.order_check.setEnabled(is_grid)
        self.row_height_spin.setEnabled(not is_grid)

    def params(self) -> dict:
        algo = self.algo_combo.currentData()
        if algo == self.ALGO_GRID:
            return {
                "algorithm": self.ALGO_GRID,
                "columns": self.columns_spin.value(),
                "gap": self.gap_spin.value(),
                "preserve_order": self.order_check.isChecked(),
            }
        return {
            "algorithm": self.ALGO_ROW_PACK,
            "target_row_height": self.row_height_spin.value(),
            "gap": self.gap_spin.value(),
        }
