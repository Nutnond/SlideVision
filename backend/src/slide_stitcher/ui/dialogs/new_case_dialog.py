from datetime import datetime

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class NewCaseDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Case")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Case name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(f"e.g., Colectomy 2024-001  (default: {self._default()})")
        layout.addWidget(self.name_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_edit.setFocus()
        self.name_edit.returnPressed.connect(self.accept)

    def name(self) -> str:
        return self.name_edit.text().strip() or self._default()

    @staticmethod
    def _default() -> str:
        return f"Case {datetime.now().strftime('%Y-%m-%d %H:%M')}"
