"""In-app update availability banner (C6)."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class UpdateBanner(QWidget):
    """Green strip under the overlay header: a new version is available.

    The banner replaces the grace-phase popup as the first thing the user
    sees when an update exists: 'What's New' opens the details popup,
    'Update' starts the update flow, and 'Later' snoozes for 24h (the
    controller records the snooze). Visibility is managed by the overlay —
    the banner is hidden while the Settings page is open and re-shown when
    Settings closes, as long as the update has not been snoozed.
    """

    whats_new_requested = pyqtSignal()
    update_requested = pyqtSignal()
    later_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("updateBanner")
        self.setStyleSheet(
            "#updateBanner { background:#162B1E; border-bottom:1px solid #1E3A2B; }"
        )

        icon = QLabel("⬆")
        icon.setStyleSheet("color:#00FF88; font-size:14px; font-weight:bold;")

        self._label = QLabel("Update available")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setStyleSheet("color:#00FF88; font-size:12px; font-weight:bold;")

        self._whats_new_btn = QPushButton("What's New")
        self._whats_new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._whats_new_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#00FF88;border:1px solid #1E3A2B;"
            "padding:4px 10px;border-radius:4px;font-size:11px;}"
            "QPushButton:hover{background:#1E3E2B;}"
        )

        self._update_btn = QPushButton("Update")
        self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_btn.setStyleSheet(
            "QPushButton{background:#00FF88;color:#0A0A0A;border:none;"
            "padding:4px 10px;border-radius:4px;font-size:11px;font-weight:bold;}"
            "QPushButton:hover{background:#33FFAA;}"
        )

        self._later_btn = QPushButton("Later")
        self._later_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._later_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#888888;border:1px solid #333333;"
            "padding:4px 10px;border-radius:4px;font-size:11px;}"
            "QPushButton:hover{background:#1E1E1E;color:#E0E0E0;}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        row.addWidget(icon)
        row.addWidget(self._label)
        row.addStretch(1)
        row.addWidget(self._whats_new_btn)
        row.addWidget(self._update_btn)
        row.addWidget(self._later_btn)

        self._whats_new_btn.clicked.connect(
            lambda _checked=False: self.whats_new_requested.emit()
        )
        self._update_btn.clicked.connect(
            lambda _checked=False: self.update_requested.emit()
        )
        self._later_btn.clicked.connect(
            lambda _checked=False: self.later_requested.emit()
        )
        self.hide()

    def set_version(self, version: str) -> None:
        """Point the banner at a specific remote version, e.g. '1.1.0'."""
        v = str(version or "").strip()
        self._label.setText(f"Version {v} is available" if v else "Update available")

    def set_ready(self, version: str) -> None:
        """C7 ready state: the installer is downloaded, verified, and one
        click away. 'Update' becomes 'Restart & install'."""
        v = str(version or "").strip()
        self._label.setText(
            f"Version {v} is ready to install" if v else "Update ready to install"
        )
        self._update_btn.setText("Restart & install")
