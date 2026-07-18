from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from slide_stitcher.models import CaseMetadata
from slide_stitcher.ui.controllers.case_controller import CaseController


class CaseCard(QFrame):
    clicked = Signal(str)  # case_id

    def __init__(self, case: CaseMetadata, controller: CaseController, parent=None) -> None:
        super().__init__(parent)
        self.case_id = case.id
        self.setObjectName("CaseCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(220, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Thumbnail (use first slide's thumb, or a placeholder)
        thumb_label = QLabel()
        thumb_label.setFixedSize(196, 110)
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet(
            "background: #1e293b; border-radius: 6px; border: 1px solid #334155;"
        )
        thumb_label.setText("🧬")
        thumb_label.setStyleSheet(
            "background: #1e293b; border-radius: 6px; border: 1px solid #334155; "
            "font-size: 36px; color: #475569;"
        )
        if case.slides:
            try:
                thumb_path = controller.thumb_path(case.slides[0].id)
                pix = QPixmap(str(thumb_path))
                if not pix.isNull():
                    thumb_label.setPixmap(
                        pix.scaled(
                            196, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                    )
                    thumb_label.setStyleSheet(
                        "background: #1e293b; border-radius: 6px; border: 1px solid #334155;"
                    )
            except Exception:
                pass
        layout.addWidget(thumb_label)

        name_label = QLabel(case.name)
        name_label.setWordWrap(True)
        name_label.setStyleSheet(
            "color: #f1f5f9; font-weight: 600; font-size: 13px; background: transparent;"
        )
        name_label.setMaximumHeight(36)
        layout.addWidget(name_label)

        try:
            date_str = datetime.fromisoformat(case.created_at).strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_str = ""
        meta_label = QLabel(f"{len(case.slides)} slides · {date_str}")
        meta_label.setStyleSheet(
            "color: #64748b; font-size: 11px; background: transparent;"
        )
        layout.addWidget(meta_label)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.case_id)
        super().mousePressEvent(event)


class WelcomeScreen(QWidget):
    newCaseRequested = Signal()
    openCaseRequested = Signal(str)  # case_id
    browseCaseRequested = Signal()

    def __init__(self, controller: CaseController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("WelcomeScreen")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(60, 50, 60, 40)
        outer.setSpacing(0)

        # Centered hero
        hero_wrap = QWidget()
        hero_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        hero = QVBoxLayout(hero_wrap)
        hero.setAlignment(Qt.AlignCenter)
        hero.setSpacing(8)

        icon_label = QLabel("🧬")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 64px; background: transparent;")
        hero.addWidget(icon_label)

        title = QLabel("SlideVision")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 32px; font-weight: 700; color: #f1f5f9; "
            "letter-spacing: -0.5px; background: transparent;"
        )
        hero.addWidget(title)

        subtitle = QLabel("Reconstruct a pathology case overview from multiple whole-slide images.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            "font-size: 14px; color: #94a3b8; background: transparent;"
        )
        hero.addWidget(subtitle)

        outer.addWidget(hero_wrap)

        # Action buttons row
        btn_wrap = QWidget()
        btn_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_layout = QHBoxLayout(btn_wrap)
        btn_layout.setAlignment(Qt.AlignCenter)
        btn_layout.setSpacing(10)

        new_btn = QPushButton("  +  New Case  ")
        new_btn.setObjectName("PrimaryButton")
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.setFixedHeight(40)
        new_btn.setStyleSheet(
            "QPushButton { background: #4f46e5; color: white; border-radius: 8px; "
            "padding: 0 24px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background: #6366f1; }"
        )
        new_btn.clicked.connect(self.newCaseRequested)
        btn_layout.addWidget(new_btn)

        browse_btn = QPushButton("  Browse all cases…  ")
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setFixedHeight(40)
        browse_btn.setStyleSheet(
            "QPushButton { background: #1e293b; color: #cbd5e1; border: 1px solid #334155; "
            "border-radius: 8px; padding: 0 18px; font-size: 13px; }"
            "QPushButton:hover { background: #334155; color: #f1f5f9; }"
        )
        browse_btn.clicked.connect(self.browseCaseRequested)
        btn_layout.addWidget(browse_btn)

        outer.addWidget(btn_wrap)

        outer.addSpacing(36)

        # Recent cases section
        self.recent_label = QLabel("Recent Cases")
        self.recent_label.setStyleSheet(
            "color: #cbd5e1; font-size: 14px; font-weight: 600; "
            "letter-spacing: 0.3px; background: transparent;"
        )
        outer.addWidget(self.recent_label)

        outer.addSpacing(14)

        # Scroll area for case cards
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")

        self.cards_container = QWidget()
        self.cards_layout = QHBoxLayout(self.cards_container)
        self.cards_layout.setAlignment(Qt.AlignLeft)
        self.cards_layout.setSpacing(14)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self.cards_container)
        outer.addWidget(self.scroll, 1)

        self.empty_recent = QLabel("No cases yet. Click “New Case” to begin.")
        self.empty_recent.setStyleSheet(
            "color: #64748b; font-size: 13px; padding: 30px; background: transparent;"
        )
        outer.addWidget(self.empty_recent)

        self._refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        # Clear existing cards
        while self.cards_layout.count():
            child = self.cards_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        cases = self.controller.list_cases()[:6]
        has_cases = len(cases) > 0
        self.recent_label.setVisible(has_cases)
        self.scroll.setVisible(has_cases)
        self.empty_recent.setVisible(not has_cases)

        for case in cases:
            card = CaseCard(case, self.controller)
            card.clicked.connect(self.openCaseRequested)
            self.cards_layout.addWidget(card)

        # Hint to use full width
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.cards_layout.addWidget(spacer)
