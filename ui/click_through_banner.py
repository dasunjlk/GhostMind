"""Non-blocking indicator for active click-through mode."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class ClickThroughBanner(QWidget):
    """Visible recovery path while mouse clicks pass through the overlay."""

    disable_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("clickThroughBanner")
        self.setStyleSheet(
            "#clickThroughBanner { background:#2A1F0D; border-bottom:1px solid #8A6D1F; }"
        )
        self.setToolTip("Ctrl+Shift+X also turns click-through off.")

        label = QLabel("Click-through is ON — clicks pass through the overlay.")
        label.setWordWrap(True)
        label.setStyleSheet("color:#FFD54F; font-size:11px; font-weight:bold;")

        self._disable_btn = QPushButton("Turn off")
        self._disable_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._disable_btn.setStyleSheet(
            "QPushButton{background:#FFD54F;color:#0A0A0A;border:none;"
            "padding:4px 10px;border-radius:4px;font-size:11px;font-weight:bold;}"
            "QPushButton:hover{background:#FFE082;}"
        )
        self._disable_btn.clicked.connect(
            lambda _checked=False: self.disable_requested.emit()
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        row.addWidget(label, 1)
        row.addWidget(self._disable_btn)
        self.hide()

    def set_active(self, active: bool) -> None:
        self.setVisible(bool(active))
