"""
GhostMind — stealth PyQt6 overlay entry point.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import toml
from dotenv import load_dotenv
from PyQt6.QtCore import QObject, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from core.ai_engine import DEFAULT_BASE_URL, DEFAULT_MODEL, resolve_api_key
from core.audio_listener import AudioListener, has_microphone
from core.question_detect import is_question
from core.screen_reader import configure_tesseract_path
from ui.overlay_window import OverlayWindow
from utils import app_paths, error_reporter, feedback, updater
from utils.hotkey_manager import HotkeyManager
from version import __version__


def check_dependencies() -> List[str]:
    """Check for required packages and return a list of warning messages."""
    warnings: List[str] = []

    # Point pytesseract at the installer-bundled Tesseract first (C11) so
    # the probe below passes on installed builds with no user-installed OCR.
    configure_tesseract_path()

    # Tesseract binary (pytesseract may be installed but tesseract.exe missing)
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:
        warnings.append(
            "Tesseract OCR not found.\n"
            "  Screen scanning (OCR) will not work.\n"
            "  Install: choco install tesseract\n"
            "  Or download from: https://github.com/UB-Mannheim/tesseract/wiki"
        )

    # OpenAI-compatible SDK (default provider: Groq)
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        warnings.append(
            "openai package not installed.\n"
            "  AI answers will not work.\n"
            "  Install: pip install openai"
        )

    # The Groq API key is optional at startup — new users paste one in
    # Settings -> API on first run. Never warn or block for it here.

    # faster-whisper — probed only in source runs. Frozen builds
    # intentionally bundle it out while audio is dormant (C12); installed
    # users must never see a "missing dependency" banner for it.
    if not getattr(sys, "frozen", False):
        try:
            from faster_whisper import WhisperModel  # noqa: F401
        except ImportError:
            warnings.append(
                "faster-whisper not installed.\n"
                "  Audio transcription will not work.\n"
                "  Install: pip install faster-whisper"
            )

    # sounddevice — same frozen-aware rule as faster-whisper (C12).
    if not getattr(sys, "frozen", False):
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            warnings.append(
                "sounddevice not installed.\n"
                "  Audio capture will not work.\n"
                "  Install: pip install sounddevice"
            )

    # keyboard
    try:
        import keyboard  # noqa: F401
    except ImportError:
        warnings.append(
            "keyboard not installed.\n"
            "  Global hotkeys will not work.\n"
            "  Install: pip install keyboard"
        )

    return warnings

# Deep link for the one-click Tesseract install (dependency dialog, R-01).
TESSERACT_URL = "https://github.com/UB-Mannheim/tesseract/wiki"

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = app_paths.data_dir()
CONFIG_PATH = app_paths.settings_path()

DEFAULT_SETTINGS: Dict[str, Any] = {
    "monitor_id": 1,
    "scan_mode": "manual",
    "auto_scan_interval_sec": 30,
    "opacity": 0.92,
    # UI text size (Preferences tab; 9-24 pt)
    "font_size": 13,
    "click_through": False,
    # C14: guided tour. Absent/False = first run → auto-starts (non-skippable);
    # completing it flips this to True; About → Replay tutorial re-runs it.
    "tutorial_done": False,
    "dwm_cloak": False,
    # v1.0: listening features hidden (future-plan.md hidden-features checklist)
    "subtitles_enabled": False,
    "capture_mic": False,
    "capture_system": False,
    "session_type": "meeting",
    "ai_model": DEFAULT_MODEL,
    # Provider endpoint (the only provider switch; no provider dropdown).
    "api_base_url": DEFAULT_BASE_URL,
    # Model IDs typed/discovered in the API tab, kept for the editable combo.
    "custom_models": [],

    "whisper_model": "base",
    "loopback_device": None,

    # Window geometry persistence (restored on launch, saved on move/resize/hide)
    "window_x": None,
    "window_y": None,
    "window_w": 480,
    "window_h": 600,
    "window_screen": None,

    "hotkeys": {
        "toggle_visibility": "ctrl+shift+g",
        "screen_scan": "ctrl+shift+s",
        "clear_answers": "ctrl+shift+c",
        "toggle_subtitles": "ctrl+shift+t",
        "export_transcript": "ctrl+shift+e",
        "toggle_click_through": "ctrl+shift+x",
        "ask_question": "ctrl+shift+q",
    },
}

LOG_PATH = app_paths.log_path()
MIGRATED_PATHS = app_paths.migrate_legacy_data(REPO_ROOT, DATA_DIR)


def _setup_logging() -> None:
    """Configure logging to console + rotating file (1 MB, keep 3 backups)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # File handler (rotating, max 1 MB x 3)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not create log file: {e}")


_setup_logging()
logger = logging.getLogger("ghostmind")
if MIGRATED_PATHS:
    logger.info("Migrated %d legacy data file(s) to %s", len(MIGRATED_PATHS), DATA_DIR)


def load_settings() -> Dict[str, Any]:
    data = dict(DEFAULT_SETTINGS)
    if CONFIG_PATH.is_file():
        try:
            disk = toml.load(CONFIG_PATH)
            if isinstance(disk, dict):
                data.update(disk)
                hk = disk.get("hotkeys")
                if isinstance(hk, dict):
                    merged = dict(data["hotkeys"])
                    merged.update(hk)
                    data["hotkeys"] = merged
        except Exception as e:
            logger.warning("Could not load %s: %s", CONFIG_PATH, e)
    return data


def save_settings(data: Dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # key_store writes secrets directly to settings.toml; never clobber them
    # with a stale in-memory snapshot (known plaintext-key loss bug).
    to_save = {k: v for k, v in data.items() if k != "key_storage"}
    try:
        if CONFIG_PATH.is_file():
            disk = toml.load(CONFIG_PATH)
            stored = disk.get("key_storage") if isinstance(disk, dict) else None
            if isinstance(stored, dict) and stored:
                to_save["key_storage"] = stored
    except Exception as e:
        logger.warning("Could not preserve stored keys in %s: %s", CONFIG_PATH, e)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        toml.dump(to_save, f)


def _create_tray_icon() -> QIcon:
    """System-tray icon from the bundled asset (C9).

    Loads assets/icon_256.png (icon.ico as fallback) from the repo root when
    running from source and from the PyInstaller bundle directory when
    frozen. The drawn green-circle glyph is kept only as a last-resort
    fallback for broken checkouts.
    """
    base = Path(getattr(sys, "_MEIPASS", REPO_ROOT))
    for name in ("icon_256.png", "icon.ico"):
        candidate = base / "assets" / name
        if candidate.is_file():
            return QIcon(str(candidate))
    logger.warning("Tray icon asset missing; using the drawn fallback glyph")
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Green circle background
    painter.setBrush(QColor("#00FF88"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    # Dark 'G' letter
    painter.setPen(QPen(QColor("#0A0A0A"), 0))
    font = QFont("Segoe UI", 30, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "G")
    painter.end()
    return QIcon(pixmap)


class _UpdateCheckWorker(QThread):
    """Runs the (network) update check off the GUI thread.

    check_for_update can block up to ~10s on an unreachable GitHub; doing that
    on the GUI thread would freeze the overlay at launch and every 6h.
    """

    done = pyqtSignal(object)  # Optional[updater.UpdateCheck]

    def __init__(self, local_version: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._local_version = local_version

    def run(self) -> None:
        try:
            result = updater.check_for_update(self._local_version)
        except Exception as e:
            logger.warning("Update check failed: %s", e)
            result = None
        self.done.emit(result)


class _UpdateDownloadWorker(QThread):
    """Background-downloads and SHA-256 verifies the new installer (C7).

    Runs after the update banner has notified the user, so by the time they
    click install the download is already finished. Failures are silent:
    the banner stays "available" and the next 6h check retries.
    """

    result = pyqtSignal(bool, str)  # ok, path-or-error

    def __init__(self, check: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._check = check

    def run(self) -> None:
        release = {"tag_name": self._check.tag, "assets": self._check.assets}
        try:
            path = updater.download_installer(release)
            self.result.emit(True, str(path))
        except updater.UpdaterError as e:
            logger.warning("Background update download failed: %s", e)
            self.result.emit(False, str(e))
        except Exception as e:
            logger.warning("Background update download failed: %s", e)
            self.result.emit(False, f"Download failed: {e}")


class _OutboxFlushWorker(QThread):
    """Silently resends feedback that failed to send last session (C13)."""

    done = pyqtSignal(int)  # count sent

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        try:
            sent = feedback.flush_outbox(DATA_DIR)
        except Exception as e:
            logger.warning("Feedback outbox flush failed: %s", e)
            sent = 0
        self.done.emit(sent)


class GhostMindController(QObject):
    """Owns hotkeys, audio thread, settings persistence, and system tray."""

    def __init__(self, app: QApplication, settings: Dict[str, Any]) -> None:
        super().__init__()
        self._app = app
        self.settings = dict(settings)
        self.overlay = OverlayWindow(self.settings, REPO_ROOT)
        self.hotkeys = HotkeyManager(self)

        # Probe audio hardware once: mic icon gets a warning badge if no input
        # device exists (Zoom-style "no microphone" indicator).
        try:
            mic_present = has_microphone()
        except Exception as e:  # never let detection block startup
            logger.warning("microphone probe failed: %s", e)
            mic_present = False
        self.overlay.set_microphone_available(mic_present)

        self._audio: Optional[AudioListener] = None
        self._meeting_timer = QTimer(self)
        self._meeting_timer.setSingleShot(True)
        self._meeting_timer.timeout.connect(self._flush_meeting_question)

        # --- Updates (U-01): 6-hour re-check + lock bookkeeping ---
        self._update_popup: Optional[Any] = None
        self._last_update_check: Optional[Any] = None
        self._update_locked = False
        self._update_worker: Optional[_UpdateCheckWorker] = None
        self._update_check_balloon = False
        # C7: background auto-download of the notified version.
        self._update_download_worker: Optional[_UpdateDownloadWorker] = None
        self._update_ready_path: Optional[str] = None
        # C13: flush unsent feedback shortly after launch (silent, best-effort).
        self._outbox_worker: Optional[_OutboxFlushWorker] = None
        QTimer.singleShot(6000, self._flush_feedback_outbox)
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(updater.CHECK_INTERVAL_SEC * 1000)
        self._update_timer.timeout.connect(lambda: self._run_update_check(show_balloon=False))
        self._update_timer.start()

        # --- System tray ---
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_create_tray_icon())
        self._tray.setToolTip("GhostMind")

        tray_menu = QMenu()
        show_action = QAction("Show overlay", self)
        show_action.triggered.connect(self._tray_show)
        tray_menu.addAction(show_action)

        hide_action = QAction("Hide overlay", self)
        hide_action.triggered.connect(self._tray_hide)
        tray_menu.addAction(hide_action)

        tray_menu.addSeparator()

        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._tray_open_settings)
        tray_menu.addAction(settings_action)

        feedback_action = QAction("Send feedback…", self)
        feedback_action.setToolTip(
            "Praise, bugs, or ideas — anonymous and privacy-safe (C13)."
        )
        feedback_action.triggered.connect(self._tray_open_feedback)
        tray_menu.addAction(feedback_action)

        self._click_through_action = QAction("Click-through: off", self)
        self._click_through_action.setCheckable(True)
        self._click_through_action.setToolTip(
            "Let mouse clicks pass through the overlay (Ctrl+Shift+X). "
            "Disabled while Settings is open."
        )
        self._click_through_action.triggered.connect(self._on_tray_click_through)
        tray_menu.addAction(self._click_through_action)

        export_action = QAction("Export transcript", self)
        export_action.triggered.connect(self.export_transcript)
        # v1.0: transcript export hidden (future-plan.md checklist).
        export_action.setVisible(False)
        tray_menu.addAction(export_action)

        tray_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._tray_quit)
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        # Tray actions hidden while the update lock is active (3.5). Transcript
        # export is v1.0-hidden separately, so it is not part of this toggle.
        self._tray_actions = [
            show_action,
            hide_action,
            settings_action,
            self._click_through_action,
        ]
        self._quit_action = quit_action
        self._tray_menu = tray_menu
        self._tray.messageClicked.connect(self._on_balloon_clicked)

        # Close button hides to tray instead of quitting
        self.overlay.close_event_allowed = False
        self.overlay.closeRequested.connect(self._tray_hide)

        self.overlay.settings_changed.connect(self._on_settings_changed)
        self.overlay.click_through_changed.connect(self._on_click_through_changed)
        self.overlay.geometry_changed.connect(self._on_geometry_changed)
        self.overlay.summarize_meeting_requested.connect(self._summarize_meeting)
        self.overlay.install_tesseract_requested.connect(
            self._open_tesseract_download
        )
        self.overlay.settings_closed.connect(self._refresh_api_key_cta)
        self.overlay.tutorial_finished.connect(self._on_tutorial_finished)
        self.overlay.update_whats_new_requested.connect(
            self._on_update_banner_whats_new
        )
        self.overlay.update_now_requested.connect(self._on_update_banner_details)
        self.overlay.update_later_requested.connect(self._on_update_banner_later)

        self.hotkeys.toggle_visibility.connect(self.overlay.toggle_visibility_animated)
        self.hotkeys.trigger_screen_scan.connect(self.overlay.trigger_screen_scan)
        self.hotkeys.clear_answers.connect(self.overlay.clear_answers)
        # v1.0: subtitles + transcript export hidden (future-plan.md checklist);
        # uncomment to rewire.
        # self.hotkeys.toggle_subtitles.connect(self.overlay.toggle_subtitles_tab)
        # self.hotkeys.export_transcript.connect(self.export_transcript)
        self.overlay.export_requested.connect(self.export_transcript)
        self.hotkeys.toggle_click_through.connect(self._toggle_click_through)
        self.hotkeys.ask_question.connect(self.overlay.focus_question_input)

        self._register_hotkeys()
        self._start_audio_if_needed()
        self._refresh_api_key_cta()
        self._sync_click_through_action()

    def _register_hotkeys(self) -> None:
        hk = self.settings.get("hotkeys", {})
        self.hotkeys.update_hotkeys(
            str(hk.get("toggle_visibility", "ctrl+shift+g")),
            str(hk.get("screen_scan", "ctrl+shift+s")),
            str(hk.get("clear_answers", "ctrl+shift+c")),
            str(hk.get("toggle_subtitles", "ctrl+shift+t")),
            str(hk.get("export_transcript", "ctrl+shift+e")),
            str(hk.get("toggle_click_through", "ctrl+shift+x")),
            str(hk.get("ask_question", "ctrl+shift+q")),
        )

    def _on_settings_changed(self, data: Dict[str, Any]) -> None:
        self.settings.update(data)
        save_settings(self.settings)
        self.overlay.apply_settings(self.settings)
        self._register_hotkeys()
        self._start_audio_if_needed()
        self._sync_click_through_action()

    def _refresh_api_key_cta(self) -> None:
        """Show the first-run API-key CTA when the current provider has no key."""
        base_url = str(self.settings.get("api_base_url") or DEFAULT_BASE_URL)
        try:
            missing = not resolve_api_key(base_url=base_url)
        except Exception as e:
            logger.warning("API key check failed: %s", e)
            missing = True
        self.overlay.set_api_key_missing(missing)

    def _on_geometry_changed(self, geom: Dict[str, Any]) -> None:
        """Persist window geometry.

        Deliberately lightweight: saving settings on every drag must NOT go
        through _on_settings_changed, which restarts the AudioListener.
        """
        self.settings.update(geom)
        save_settings(self.settings)

    def _start_audio_if_needed(self) -> None:
        # v1.0: mic/system listening is not part of the first release. Remove this
        # guard to re-enable (see future-plan.md hidden-features checklist).
        return
        if self._audio is not None:
            self._audio.stop_listening()
            self._audio = None
        if not self.settings.get("subtitles_enabled", True):
            return
        if not self.settings.get("capture_mic", True) and not self.settings.get(
            "capture_system", True
        ):
            return
        loop_dev = self.settings.get("loopback_device")
        if loop_dev is not None:
            try:
                loop_dev = int(loop_dev)
            except (TypeError, ValueError):
                loop_dev = None
        session_type = str(self.settings.get("session_type", "meeting"))
        self._audio = AudioListener(
            capture_mic=bool(self.settings.get("capture_mic", True)),
            capture_system=bool(self.settings.get("capture_system", True)),
            loopback_device=loop_dev,
            model_size=str(self.settings.get("whisper_model", "base")),
            session_type=session_type,
        )
        self._audio.subtitle_updated.connect(self._on_subtitle_line)
        self._audio.failed.connect(self._on_audio_failed)
        self._audio.start_listening()

    def _on_audio_failed(self, msg: str) -> None:
        logger.error("Audio: %s", msg)
        self.overlay._answer_panel.end_stream_error(f"Audio: {msg}")

    def _on_subtitle_line(self, line: str) -> None:
        self.overlay.push_subtitle_line(line)
        # Fast question detection based on '?' or question words
        is_q = is_question(line)
        if is_q:
            self._meeting_timer.start(1200)

    def _summarize_meeting(self) -> None:
        """Summarize all transcript captured so far."""
        if self._audio is None:
            self.overlay._answer_panel.end_stream_error("No audio capture is currently active.")
            return
        snap = self._audio.full_transcript()
        if not snap:
            self.overlay._answer_panel.end_stream_error("No audio transcript recorded yet to summarize.")
            return
        st = str(self.settings.get("session_type", "meeting"))
        lines = [f"{src}: {txt}" for _ts, src, txt in snap]
        text = "\n".join(lines)
        context_type = "lecture_notes" if st == "lecture" else "meeting_summary"
        self.overlay.request_ai_answer(text, context_type)

    def _open_tesseract_download(self) -> None:
        QDesktopServices.openUrl(QUrl(TESSERACT_URL))

    # --- tray actions ---
    def _tray_show(self) -> None:
        if self._update_locked:
            return  # overlay stays hidden while the update lock is active
        if not self.overlay.isVisible():
            self.overlay.toggle_visibility_animated()

    def _tray_hide(self) -> None:
        if self._update_locked:
            return
        if self.overlay.isVisible():
            self.overlay.toggle_visibility_animated()

    def _tray_open_settings(self) -> None:
        """Tray recovery path: show the overlay and open Settings."""
        if self._update_locked:
            return
        self._tray_show()
        self.overlay.open_settings()

    def _tray_open_feedback(self) -> None:
        """Tray path to the Feedback tab (C13)."""
        if self._update_locked:
            return
        self._tray_show()
        self.overlay.open_feedback_settings()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self._update_locked:
                if self._last_update_check is not None:
                    self._show_update_popup(self._last_update_check, locked=True)
                return
            self.overlay.toggle_visibility_animated()

    def _tray_quit(self) -> None:
        self._tray.hide()
        self._app.quit()

    def _toggle_click_through(self) -> None:
        """Toggle click-through mode on/off with a hotkey."""
        self._set_click_through(not bool(self.settings.get("click_through", False)))

    def _on_tray_click_through(self, checked: bool) -> None:
        self._set_click_through(bool(checked))

    def _set_click_through(self, on: bool) -> None:
        if on and self.overlay.is_settings_open():
            self._sync_click_through_action()
            self._tray.showMessage(
                "GhostMind",
                "Close Settings before enabling click-through.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
            return
        self.settings["click_through"] = bool(on)
        save_settings(self.settings)
        self.overlay.set_click_through(bool(on))
        self._sync_click_through_action()
        self._notify_click_through(bool(on))

    def _sync_click_through_action(self) -> None:
        on = bool(self.settings.get("click_through", False))
        self._click_through_action.blockSignals(True)
        self._click_through_action.setChecked(on)
        self._click_through_action.setText(
            "Click-through: on" if on else "Click-through: off"
        )
        self._click_through_action.blockSignals(False)
        self._tray.setToolTip("GhostMind — click-through ON" if on else "GhostMind")

    def _notify_click_through(self, on: bool) -> None:
        if on:
            message = (
                "Click-through: ON — clicks pass through. Use the banner, "
                "tray menu, or Ctrl+Shift+X to turn it off."
            )
        else:
            message = "Click-through: OFF — clicks interact with the overlay."
        self._tray.showMessage(
            "GhostMind",
            message,
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def _on_click_through_changed(self, on: bool) -> None:
        """Overlay changed click-through: persist and sync the tray action."""
        self.settings["click_through"] = bool(on)
        save_settings(self.settings)
        self._sync_click_through_action()

    # --- transcript export ---
    def export_transcript(self) -> None:
        """Open a save dialog and export the full transcript to .txt or .md."""
        if self._audio is None:
            QMessageBox.information(
                self.overlay,
                "Export",
                "No audio capture is active. Enable subtitles in settings to record a transcript.",
            )
            return

        snapshot = self._audio.full_transcript()
        if not snapshot:
            QMessageBox.information(
                self.overlay,
                "Export",
                "Transcript is empty. Nothing to export.",
            )
            return

        default_name = f"ghostmind_transcript_{datetime.now():%Y%m%d_%H%M%S}"
        path, selected_filter = QFileDialog.getSaveFileName(
            self.overlay,
            "Export Transcript",
            str(REPO_ROOT / f"{default_name}.txt"),
            "Text files (*.txt);;Markdown (*.md);;All files (*)",
        )
        if not path:
            return

        # Determine format from chosen path or filter
        is_md = path.endswith(".md") or "Markdown" in selected_filter
        content = self._format_transcript(snapshot, as_markdown=is_md)

        try:
            Path(path).write_text(content, encoding="utf-8")
            self._tray.showMessage(
                "GhostMind",
                f"Transcript exported to {Path(path).name}",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        except Exception as e:
            logger.error("Export failed: %s", e)
            QMessageBox.warning(self.overlay, "Export failed", str(e))

    @staticmethod
    def _format_transcript(
        snapshot: List[Tuple[float, str, str]], as_markdown: bool = False
    ) -> str:
        """Format transcript entries into plain text or markdown."""
        if as_markdown:
            lines = ["# GhostMind Transcript\n"]
            lines.append(f"_Exported {datetime.now():%Y-%m-%d %H:%M:%S}_\n")
            lines.append("---\n")
            for ts, source, text in snapshot:
                t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                lines.append(f"**[{t}] {source}:** {text}\n")
            return "\n".join(lines)
        else:
            lines = ["GhostMind Transcript"]
            lines.append(f"Exported {datetime.now():%Y-%m-%d %H:%M:%S}")
            lines.append("=" * 40 + "\n")
            for ts, source, text in snapshot:
                t = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                lines.append(f"[{t}] {source}: {text}")
            return "\n".join(lines)

    def _flush_meeting_question(self) -> None:
        if self._audio is None:
            return
        snap = self._audio.transcript_snapshot()
        if not snap:
            return
        lines = [f"{src}: {txt}" for _ts, src, txt in snap]
        text = "\n".join(lines)
        st = str(self.settings.get("session_type", "meeting"))
        context_type = "meeting_question" if "?" in text else ("meeting_audio" if st == "meeting" else "lecture_notes")
        self.overlay.request_ai_answer(text, context_type)

    # --- feedback (C13) -------------------------------------------------------

    def _flush_feedback_outbox(self) -> None:
        """Resend feedback that failed last session (never blocks, never nags)."""
        if self._outbox_worker is not None and self._outbox_worker.isRunning():
            return
        worker = _OutboxFlushWorker(self)
        self._outbox_worker = worker
        worker.done.connect(lambda _count: None)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "_outbox_worker", None))
        worker.start()

    # --- tutorial (C14) -------------------------------------------------------

    def _on_tutorial_finished(self, completed: bool) -> None:
        """Persist first-run tour completion (lightweight — no full apply)."""
        if not completed:
            return
        self.settings["tutorial_done"] = True
        save_settings(self.settings)
        logger.info("First-run tutorial completed")

    # --- updates (U-01) -----------------------------------------------------

    def initial_update_check(self) -> None:
        """Launch-time check (deferred by a QTimer in main() so startup never blocks)."""
        self._run_update_check(show_balloon=True)

    def _run_update_check(self, show_balloon: bool = False) -> None:
        """Start the update check in the background (never block the GUI)."""
        if self._update_worker is not None and self._update_worker.isRunning():
            return  # 6h timer or balloon click while a check is in flight
        worker = _UpdateCheckWorker(__version__, self)
        self._update_worker = worker
        self._update_check_balloon = show_balloon
        worker.done.connect(self._on_update_check_done)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._on_update_worker_finished)
        worker.start()

    def _on_update_worker_finished(self) -> None:
        self._update_worker = None

    def _on_update_check_done(self, result: Any) -> None:
        if result is None:
            return  # offline / rate-limited → silently skip (never nag, never lock)
        self._last_update_check = result
        if not result.update_available:
            return
        if self._update_check_balloon and result.first_popup_for_version:
            self._tray.showMessage(
                "GhostMind",
                f"GhostMind {result.tag} available — click for details",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
        if result.locked:
            self._enter_update_lock(result)
        else:
            # C6: the grace phase surfaces as an in-app banner, not a popup.
            self._show_update_banner(result)

    def _show_update_banner(self, check: Any) -> None:
        """Show the in-app banner unless this version is currently snoozed."""
        state = getattr(check, "state", None) or {}
        now = int(getattr(check, "now", 0) or time.time())
        if now < int(state.get("snooze_until_epoch") or 0):
            self.overlay.hide_update_banner()
            return
        tag = str(getattr(check, "tag", "") or "")
        # C7: a previously verified download for THIS version flips the
        # banner straight to "ready to install" (survives restarts).
        if (
            state.get("downloaded_version") == tag
            and state.get("downloaded_sha_ok")
            and Path(str(state.get("downloaded_path") or "")).is_file()
        ):
            self._update_ready_path = str(state.get("downloaded_path"))
            self.overlay.show_update_banner(tag, ready=True)
            return
        self._update_ready_path = None
        self.overlay.show_update_banner(tag)
        self._maybe_auto_download(check)

    def _maybe_auto_download(self, check: Any) -> None:
        """C7: the user has been notified — fetch the installer in the background."""
        if self._update_download_worker is not None and self._update_download_worker.isRunning():
            return
        worker = _UpdateDownloadWorker(check, self)
        self._update_download_worker = worker
        worker.result.connect(self._on_update_download_result)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._on_update_download_worker_finished)
        worker.start()

    def _on_update_download_worker_finished(self) -> None:
        self._update_download_worker = None

    def _on_update_download_result(self, ok: bool, message: str) -> None:
        if not ok:
            # Silent: the banner stays "available"; the next 6h check retries
            # and record_failed_attempt has already fed the safety valve.
            return
        self._update_ready_path = message
        check = self._last_update_check
        tag = str(getattr(check, "tag", "") or "") if check is not None else ""
        self.overlay.show_update_banner(tag, ready=True)

    def _run_downloaded_installer(self, path: str) -> None:
        """C7 one-click install: run the verified installer; the app must exit
        so Inno Setup can replace its files (same contract as the popup flow)."""
        try:
            os.startfile(path)
            updater.record_popup()
            app = QApplication.instance()
            if app is not None:
                app.quit()
        except Exception as e:
            logger.warning("Could not start downloaded installer %s: %s", path, e)

    def _on_update_banner_whats_new(self) -> None:
        """'What's New' always opens the details popup (C8 makes it read as
        plain-language What's New bullets)."""
        if self._last_update_check is None or not self._last_update_check.update_available:
            return
        self._show_update_popup(
            self._last_update_check, locked=bool(self._last_update_check.locked)
        )

    def _on_update_banner_details(self) -> None:
        """'Update' one-click-installs the pre-downloaded installer (C7);
        otherwise it opens the details popup like 'What's New'."""
        if self._update_ready_path and Path(self._update_ready_path).is_file():
            self._run_downloaded_installer(self._update_ready_path)
            return
        self._on_update_banner_whats_new()

    def _on_update_banner_later(self) -> None:
        updater.record_snooze()
        self.overlay.hide_update_banner()

    def _show_update_popup(self, check: Any, locked: bool) -> None:
        # Never stack popups (6h timer can fire while one is open).
        if self._update_popup is not None and self._update_popup.isVisible():
            return
        from ui.update_popup import UpdatePopup

        self._update_popup = UpdatePopup(check, locked=locked)
        self._update_popup.finished.connect(self._on_update_popup_finished)
        self._update_popup.show()
        self._update_popup.raise_()
        self._update_popup.activateWindow()

    def _restore_from_update_lock(self) -> None:
        """Undo _enter_update_lock (safety valve bought the user 24h)."""
        if not self._update_locked:
            return
        self._update_locked = False
        self.overlay.setEnabled(True)
        self._register_hotkeys()
        for act in self._tray_actions:
            act.setVisible(True)
        if hasattr(self, "_update_tray_action"):
            self._update_tray_action.setVisible(False)
        logger.info("Update lock lifted via safety valve (24h snooze)")

    def _on_update_popup_finished(self, _result: int) -> None:
        # The safety valve snoozes ~24h; if the state file now has an active
        # snooze, restore the UI immediately instead of waiting for the next check.
        state = updater.load_state()
        if int(state.get("snooze_until_epoch") or 0) > time.time():
            self._restore_from_update_lock()
            self.overlay.hide_update_banner()

    def _enter_update_lock(self, check: Any) -> None:
        """Grace expired: hide overlay, kill hotkeys, reduce tray, force popup."""
        if self._update_locked and self._update_popup is not None and self._update_popup.isVisible():
            return
        self._update_locked = True
        logger.warning("Update lock engaged (newer version %s, grace expired)", check.tag)
        self.overlay.hide_update_banner()
        if self.overlay.isVisible():
            self.overlay.toggle_visibility_animated()
        self.overlay.setEnabled(False)
        self.hotkeys.unregister_all()
        for act in self._tray_actions:
            act.setVisible(False)
        if not hasattr(self, "_update_tray_action"):
            self._tray_menu.insertSeparator(self._quit_action)
            self._update_tray_action = QAction("Update now", self)
            self._update_tray_action.triggered.connect(
                lambda: self._last_update_check and self._show_update_popup(self._last_update_check, locked=True)
            )
            self._tray_menu.insertAction(self._quit_action, self._update_tray_action)
        self._update_tray_action.setVisible(True)
        self._show_update_popup(check, locked=True)

    def _on_balloon_clicked(self) -> None:
        if self._last_update_check is not None and self._last_update_check.update_available:
            if self._last_update_check.locked or self._update_locked:
                self._show_update_popup(self._last_update_check, locked=True)
            else:
                self._show_update_popup(self._last_update_check, locked=False)


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("GhostMind")

    # Anonymous error reporting (Sentry). No-op until a DSN is configured;
    # fully disabled by GHOSTMIND_NO_TELEMETRY=1.
    error_reporter.install(DATA_DIR)

    # Default UI font: prefer the branded faces when installed, else Segoe UI.
    # (Individual widgets may still set their own; this is the app-wide base.)
    _fam = {f.lower() for f in QFontDatabase.families()}
    _preferred = next((f for f in ("Inter", "DM Sans", "JetBrains Mono", "Segoe UI")
                       if f.lower() in _fam), None)
    if _preferred:
        app.setFont(QFont(_preferred, 10))

    # App-wide dark-theme polish: consistent tooltips, menus, inputs, scrollbars.
    app.setStyleSheet(
        ""
        "QToolTip { color:#E0E0E0; background:#1A1A1A; border:1px solid #00FF88; padding:4px; }"
        "QMenu { background:#141414; color:#E0E0E0; border:1px solid #333; }"
        "QMenu::item:selected { background:#162B1E; color:#00FF88; }"
        "QComboBox { background:#141414; color:#E0E0E0; border:1px solid #333;"
        "  border-radius:4px; padding:3px 8px; }"
        "QComboBox QAbstractItemView { background:#141414; color:#E0E0E0;"
        "  selection-background-color:#162B1E; selection-color:#00FF88; }"
        "QSpinBox { background:#141414; color:#E0E0E0; border:1px solid #333;"
        "  border-radius:4px; padding:2px 6px; }"
        "QLineEdit { background:#141414; color:#E0E0E0; border:1px solid #333;"
        "  border-radius:4px; padding:3px 6px; }"
        "QPushButton { font-size:12px; }"
        "QScrollBar:vertical { background:#111; width:8px; border:none; }"
        "QScrollBar::handle:vertical { background:#2A5A40; border-radius:4px; min-height:24px; }"
        "QScrollBar::handle:vertical:hover { background:#00FF88; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
        "QScrollBar:horizontal { background:#111; height:8px; border:none; }"
        "QScrollBar::handle:horizontal { background:#2A5A40; border-radius:4px; min-width:24px; }"
        "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }"
    )

    # Startup dependency check (shown as a non-blocking overlay banner)
    warnings = check_dependencies()
    if warnings:
        logger.warning("Startup dependency warnings: %s", "; ".join(warnings))

    settings = load_settings()
    ctrl = GhostMindController(app, settings)
    if warnings:
        ctrl.overlay.show_dependency_warnings(warnings)

    # U-01: first update check shortly after launch (network must not block startup)
    QTimer.singleShot(1500, ctrl.initial_update_check)

    def _sigint(*_args) -> None:
        logger.info("SIGINT — quitting")
        app.quit()

    signal.signal(signal.SIGINT, _sigint)
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(400)

    app.aboutToQuit.connect(ctrl.hotkeys.unregister_all)
    app.aboutToQuit.connect(error_reporter.flush)

    ctrl.overlay.show()
    try:
        hwnd = int(ctrl.overlay.winId())
        from core.stealth import apply_stealth

        apply_stealth(
            hwnd,
            click_through=bool(ctrl.settings.get("click_through", False)),
            dwm_cloak=bool(ctrl.settings.get("dwm_cloak", False)),
        )
    except Exception as e:
        logger.warning("Initial stealth apply failed: %s", e)
    # C14: first-run guided tour (non-skippable, per the implementation plan).
    QTimer.singleShot(800, ctrl.overlay.maybe_start_first_run_tutorial)

    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
