"""Non-modal startup dependency warning strip."""
from __future__ import annotations

from typing import Iterable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class DependencyBanner(QWidget):
    """Inline warning strip shown under the overlay header.

    Unlike the old startup QMessageBox, this never blocks input: the overlay
    (including the Settings gear) stays usable while the warning is visible.
    """

    install_tesseract_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    dismissed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dependencyBanner")
        self.setStyleSheet(
            "#dependencyBanner { background:#2A210D; border-bottom:1px solid #6B5416; }"
        )

        title = QLabel("Setup needed")
        title.setStyleSheet("color:#FFD54F; font-weight:bold; font-size:12px;")

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._label.setStyleSheet("color:#E8D9A8; font-size:11px;")

        self._install_btn = QPushButton("Install Tesseract")
        self._install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_btn.setStyleSheet(
            "QPushButton{background:#FFD54F;color:#0A0A0A;border:none;"
            "padding:4px 10px;border-radius:4px;font-size:11px;font-weight:bold;}"
            "QPushButton:hover{background:#FFE082;}"
        )
        self._install_btn.hide()

        self._settings_btn = QPushButton("Open Settings")
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#FFD54F;border:1px solid #6B5416;"
            "padding:4px 10px;border-radius:4px;font-size:11px;}"
            "QPushButton:hover{background:#3A2E12;}"
        )

        self._dismiss_btn = QPushButton("Dismiss")
        self._dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismiss_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#A89B77;border:1px solid #4A3E1C;"
            "padding:4px 10px;border-radius:4px;font-size:11px;}"
            "QPushButton:hover{background:#3A2E12;color:#E8D9A8;}"
        )

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addStretch(1)
        buttons.addWidget(self._install_btn)
        buttons.addWidget(self._settings_btn)
        buttons.addWidget(self._dismiss_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(4)
        layout.addWidget(title)
        layout.addWidget(self._label)
        layout.addLayout(buttons)

        self._install_btn.clicked.connect(
            lambda _checked=False: self.install_tesseract_requested.emit()
        )
        self._settings_btn.clicked.connect(
            lambda _checked=False: self.settings_requested.emit()
        )
        self._dismiss_btn.clicked.connect(self._dismiss)
        self.hide()

    def show_warnings(self, warnings: Iterable[str]) -> None:
        messages = [str(w).strip() for w in warnings if str(w).strip()]
        if not messages:
            self.hide()
            return
        self._label.setText("\n\n".join(messages))
        self._install_btn.setVisible(
            any("Tesseract OCR not found" in m for m in messages)
        )
        self.show()

    def _dismiss(self) -> None:
        self.hide()
        self.dismissed.emit()
