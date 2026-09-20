"""
U-01 update popup: grace-phase dialog and locked application-modal window.

Phase 1 (day 0..4): closable; "Later" snoozes 24h.
Phase 2 (day 5+): cannot be closed — Esc, Alt+F4 and the X are all blocked;
the user must update (with the 24h safety valve after repeated failures).
The "Update Now" flow downloads GhostMind-Setup-<ver>.exe to %TEMP%, verifies
SHA256 against SHA256SUMS.txt, then runs the installer.

NOTE (plan 3.5): unlike the main overlay, this window must stay visible in
screen shares — no WDA_EXCLUDEFROMCAPTURE / stealth flags are applied here.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

from PyQt6.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import utils.updater as updater
from utils.updater import MAX_CONSECUTIVE_FAILURES
from version import __version__

logger = logging.getLogger(__name__)


class _UpdateSignals(QObject):
    download_progress = pyqtSignal(int, int)   # received, total
    download_done = pyqtSignal(bool, str)      # ok, message (path or error)


class UpdatePopup(QDialog):
    """One dialog that renders either the grace phase or the locked phase."""

    def __init__(
        self,
        check: "updater.UpdateCheck",
        locked: bool,
        state_path=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._check = check
        self._locked = locked
        self._state_path = state_path or updater.STATE_PATH
        self._installer_path: Optional[Any] = None
        self._downloading = False

        self._signals = _UpdateSignals(self)
        self._signals.download_progress.connect(self._on_progress)
        self._signals.download_done.connect(self._on_download_done)

        self.setWindowTitle("Update required" if locked else "GhostMind update available")
        self.setModal(True)
        if locked:
            # Application-modal, no close button, no system menu, always on top.
            self.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.CustomizeWindowHint
                | Qt.WindowType.WindowTitleHint
            )
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        else:
            self.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.WindowCloseButtonHint
                | Qt.WindowType.WindowMinimizeButtonHint
            )
        self.setMinimumSize(460, 320)
        self._build_ui()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        headline = QLabel(
            f"Version {self._check.tag} is available (you have {__version__})."
        )
        headline.setStyleSheet("color:#00FF88;font-weight:bold;font-size:14px;")
        root.addWidget(headline)

        if not self._locked and self._check.days_left > 0:
            grace = QLabel(
                f"Update recommended. You can keep using this version for "
                f"{self._check.days_left} more day"
                f"{'s' if self._check.days_left != 1 else ''}."
            )
            grace.setStyleSheet("color:#CCCCCC;font-size:12px;")
            root.addWidget(grace)
        elif self._locked:
            locked_msg = QLabel(
                f"Your version ({__version__}) is no longer supported.\n"
                f"Update to {self._check.tag} to continue using GhostMind."
            )
            locked_msg.setStyleSheet("color:#FF6666;font-size:12px;")
            root.addWidget(locked_msg)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(self._check.notes or "No release notes provided.")
        notes.setStyleSheet(
            "QTextEdit{background:#0E0E0E;color:#BBBBBB;border:1px solid #1E3A2B;"
            "border-radius:4px;font-size:11px;}"
        )
        notes.setMaximumHeight(220)
        root.addWidget(notes, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#777777;font-size:11px;")
        root.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setRange(0, 100)
        root.addWidget(self._progress)

        buttons = QHBoxLayout()
        self._update_btn = QPushButton("Update Now")
        self._update_btn.setStyleSheet(
            "QPushButton{background:#00FF88;color:#0A0A0A;border:none;"
            "padding:7px 18px;font-weight:bold;border-radius:4px;}"
            "QPushButton:hover{background:#33FFAA;}"
            "QPushButton:disabled{background:#333;color:#777;}"
        )
        self._update_btn.clicked.connect(self._on_update_now)
        buttons.addWidget(self._update_btn)

        self._valve_btn = QPushButton("Continue for 24 hours")
        self._valve_btn.setStyleSheet(
            "QPushButton{background:#141414;color:#CCCCCC;border:1px solid #333;"
            "padding:6px 12px;border-radius:4px;font-size:11px;}"
            "QPushButton:hover{background:#202020;}"
        )
        self._valve_btn.setVisible(False)
        self._valve_btn.clicked.connect(self._on_safety_valve)
        buttons.addWidget(self._valve_btn)

        buttons.addStretch(1)

        page_btn = QPushButton("Open release page in browser")
        page_btn.setStyleSheet(
            "QPushButton{background:#141414;color:#00AAFF;border:1px solid #113;"
            "padding:6px 12px;border-radius:4px;font-size:11px;}"
            "QPushButton:hover{background:#101820;}"
        )
        page_btn.clicked.connect(self._open_release_page)
        buttons.addWidget(page_btn)

        if not self._locked:
            later_btn = QPushButton("Later")
            later_btn.setStyleSheet(
                "QPushButton{background:#1A1A1A;color:#CCCCCC;border:1px solid #333;"
                "padding:7px 14px;border-radius:4px;}"
                "QPushButton:hover{background:#252525;}"
            )
            later_btn.clicked.connect(self._on_later)
            buttons.addWidget(later_btn)

        root.addLayout(buttons)
        self._refresh_valve_visibility()

    # ------------------------------------------------------------- events --

    def reject(self) -> None:  # Esc key
        if self._locked or self._downloading:
            return
        self._on_later()

    def closeEvent(self, event) -> None:  # X / Alt+F4
        if self._locked or self._downloading:
            event.ignore()
            return
        self._on_later()
        event.accept()

    # ------------------------------------------------------------ actions --

    def _on_later(self) -> None:
        updater.record_popup(self._state_path)
        updater.record_snooze(self._state_path)
        self.done(QDialog.DialogCode.Rejected)

    def _on_update_now(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self._update_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._status.setText("Downloading installer…")
        release = {
            "tag_name": self._check.tag,
            "assets": self._check.assets,
        }
        state_path = self._state_path

        def _work() -> None:
            try:
                path = updater.download_installer(
                    release,
                    progress_cb=lambda recv, total: self._signals.download_progress.emit(
                        recv, total
                    ),
                    state_path=state_path,
                )
                self._signals.download_done.emit(True, str(path))
            except updater.UpdaterError as e:
                self._signals.download_done.emit(False, str(e))
            except Exception as e:
                self._signals.download_done.emit(False, f"Download failed: {e}")

        threading.Thread(target=_work, daemon=True).start()

    def _on_progress(self, received: int, total: int) -> None:
        if total > 0:
            self._progress.setRange(0, 100)
            self._progress.setValue(int(received * 100 / total))
            self._status.setText(
                f"Downloading installer… {received // 1_048_576} / {total // 1_048_576} MB"
            )
        else:
            self._progress.setRange(0, 0)  # indeterminate
            self._status.setText(f"Downloading installer… {received // 1_048_576} MB")

    def _on_download_done(self, ok: bool, msg: str) -> None:
        self._downloading = False
        if ok:
            self._installer_path = msg
            self._progress.setValue(100)
            self._status.setText(
                "Installer downloaded and verified. It will close GhostMind — "
                "start GhostMind again when the installer finishes."
            )
            self._update_btn.setText("Restart installer")
            self._update_btn.setEnabled(True)
            # Re-click runs the installer instead of downloading again.
            try:
                self._update_btn.clicked.disconnect(self._on_update_now)
            except TypeError:
                pass
            self._update_btn.clicked.connect(self._run_installer)
        else:
            self._progress.setVisible(False)
            self._status.setText(f"● {msg}")
            self._status.setStyleSheet("color:#FF5555;font-size:11px;")
            self._update_btn.setEnabled(True)
            self._refresh_valve_visibility()

    def _run_installer(self) -> None:
        if not self._installer_path:
            return
        try:
            os.startfile(self._installer_path)
            updater.record_popup(self._state_path)
            self.done(QDialog.DialogCode.Accepted)
        except Exception as e:
            self._status.setText(f"● Could not start installer: {e}")
            self._status.setStyleSheet("color:#FF5555;font-size:11px;")

    def _open_release_page(self) -> None:
        QDesktopServices.openUrl(_github_releases_url())

    def _on_safety_valve(self) -> None:
        """24h unlock (plan 3.6): re-locks automatically afterwards."""
        import time

        updater.record_snooze(self._state_path, int(time.time()) + updater.POPUP_SNOOZE_SEC)
        updater.reset_failed_attempts(self._state_path)
        self.done(QDialog.DialogCode.Accepted)

    def _refresh_valve_visibility(self) -> None:
        # Safety valve appears once the grace is over and downloads keep failing.
        attempts = int(
            updater.load_state(self._state_path).get("failed_attempts") or 0
        )
        show = self._locked and attempts >= MAX_CONSECUTIVE_FAILURES
        self._valve_btn.setVisible(show)


def _github_releases_url() -> QUrl:
    return QUrl(updater.DEFAULT_UPDATE_URL.replace("/releases/latest", "/releases"))
