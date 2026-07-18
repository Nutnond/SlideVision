from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)


class CropDialog(QDialog):
    def __init__(
        self,
        initial: tuple[float, float, float, float],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crop Slide")
        self.setMinimumWidth(420)

        self._crop = initial
        self._on_apply = None

        layout = QVBoxLayout(self)

        hint = QLabel(
            "Crop values are normalized 0–1.\n"
            "Left = crop_x · Top = crop_y · Width = crop_w · Height = crop_h"
        )
        hint.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(hint)

        form = QFormLayout()
        self.sl_x = self._make_slider(self._crop[0], 0, 100)
        self.sl_y = self._make_slider(self._crop[1], 0, 100)
        self.sl_w = self._make_slider(self._crop[2], 1, 100)
        self.sl_h = self._make_slider(self._crop[3], 1, 100)
        self.lbl_x = QLabel(f"{self._crop[0]:.2f}")
        self.lbl_y = QLabel(f"{self._crop[1]:.2f}")
        self.lbl_w = QLabel(f"{self._crop[2]:.2f}")
        self.lbl_h = QLabel(f"{self._crop[3]:.2f}")

        self.sl_x.valueChanged.connect(lambda v: self._on_change("x", v))
        self.sl_y.valueChanged.connect(lambda v: self._on_change("y", v))
        self.sl_w.valueChanged.connect(lambda v: self._on_change("w", v))
        self.sl_h.valueChanged.connect(lambda v: self._on_change("h", v))

        form.addRow("Left (x):", self._row(self.sl_x, self.lbl_x))
        form.addRow("Top (y):", self._row(self.sl_y, self.lbl_y))
        form.addRow("Width (w):", self._row(self.sl_w, self.lbl_w))
        form.addRow("Height (h):", self._row(self.sl_h, self.lbl_h))
        layout.addLayout(form)

        reset_btn = QPushButton("Reset to full")
        reset_btn.clicked.connect(self._reset)
        layout.addWidget(reset_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_slider(self, initial: float, lo: int, hi: int) -> QSlider:
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(int(initial * 100))
        return s

    def _row(self, slider: QSlider, label: QLabel):
        w = QHBoxLayout()
        w.addWidget(slider, 1)
        w.addWidget(label)
        return w

    def _on_change(self, key: str, value: int) -> None:
        v = value / 100.0
        cx, cy, cw, ch = self._crop
        if key == "x":
            cx = v
            if cx + cw > 1.0:
                cw = 1.0 - cx
                self.sl_w.setValue(int(cw * 100))
                self.lbl_w.setText(f"{cw:.2f}")
        elif key == "y":
            cy = v
            if cy + ch > 1.0:
                ch = 1.0 - cy
                self.sl_h.setValue(int(ch * 100))
                self.lbl_h.setText(f"{ch:.2f}")
        elif key == "w":
            cw = min(v, 1.0 - cx)
            v = int(cw * 100)
            if self.sl_w.value() != v:
                self.sl_w.setValue(v)
            cw_v = cw
        elif key == "h":
            ch = min(v, 1.0 - cy)
            v = int(ch * 100)
            if self.sl_h.value() != v:
                self.sl_h.setValue(v)
            ch_v = ch

        cx, cy, cw, ch = self._read_sliders()
        self._crop = (cx, cy, cw, ch)
        self.lbl_x.setText(f"{cx:.2f}")
        self.lbl_y.setText(f"{cy:.2f}")
        self.lbl_w.setText(f"{cw:.2f}")
        self.lbl_h.setText(f"{ch:.2f}")
        if self._on_apply:
            self._on_apply(self._crop)

    def _read_sliders(self) -> tuple[float, float, float, float]:
        cx = self.sl_x.value() / 100.0
        cy = self.sl_y.value() / 100.0
        cw = self.sl_w.value() / 100.0
        ch = self.sl_h.value() / 100.0
        cw = min(cw, 1.0 - cx)
        ch = min(ch, 1.0 - cy)
        return cx, cy, cw, ch

    def _reset(self) -> None:
        self.sl_x.setValue(0)
        self.sl_y.setValue(0)
        self.sl_w.setValue(100)
        self.sl_h.setValue(100)
        self._on_change("x", 0)

    def on_apply(self, callback) -> None:
        self._on_apply = callback

    def value(self) -> tuple[float, float, float, float]:
        return self._read_sliders()
