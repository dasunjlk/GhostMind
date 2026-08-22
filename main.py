"""
GhostMind — stealth PyQt6 overlay entry point.
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import toml
from dotenv import load_dotenv
from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QAction, QIcon, QPainter, QColor, QPen, QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from core.audio_listener import AudioListener
from ui.overlay_window import OverlayWindow
from utils.hotkey_manager import HotkeyManager

REPO_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = REPO_ROOT / "config" / "settings.toml"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "monitor_id": 1,
    "scan_mode": "manual",
    "auto_scan_interval_sec": 30,
    "opacity": 0.92,
    "click_through": False,
    "dwm_cloak": False,
    "subtitles_enabled": True,
    "capture_mic": True,
    "capture_system": False,
    "whisper_model": "base",
    "loopback_device": None,
    "hotkeys": {
        "toggle_visibility": "ctrl+shift+g",
        "screen_scan": "ctrl+shift+s",
        "clear_answers": "ctrl+shift+c",
        "toggle_subtitles": "ctrl+shift+t",
        "export_transcript": "ctrl+shift+e",
    },
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ghostmind")


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
    to_save = {k: v for k, v in data.items()}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        toml.dump(to_save, f)


def _create_tray_icon() -> QIcon:
    """Create a green-circle tray icon with 'G' letter programmatically."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#00FF88"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.setPen(QPen(QColor("#0A0A0A"), 0))
    font = QFont("Segoe UI", 30, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "G")
    painter.end()
    return QIcon(pixmap)


class GhostMindController(QObject):
    """Owns hotkeys, audio thread, settings persistence, and system tray."""

    def __init__(self, app: QApplication, settings: Dict[str, Any]) -> None:
        super().__init__()
        self._app = app
        self.settings = dict(settings)
        self.overlay = OverlayWindow(self.settings, REPO_ROOT)
        self.hotkeys = HotkeyManager(self)

        self._audio: Optional[AudioListener] = None
        self._meeting_timer = QTimer(self)
        self._meeting_timer.setSingleShot(True)
        self._meeting_timer.timeout.connect(self._flush_meeting_question)

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

        export_action = QAction("Export transcript", self)
        export_action.triggered.connect(self.export_transcript)
        tray_menu.addAction(export_action)

        tray_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._tray_quit)
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        # Close button hides to tray instead of quitting
        self.overlay.close_event_allowed = False
        self.overlay.closeRequested.connect(self._tray_hide)

        self.overlay.settings_changed.connect(self._on_settings_changed)

        self.hotkeys.toggle_visibility.connect(self.overlay.toggle_visibility_animated)
        self.hotkeys.trigger_screen_scan.connect(self.overlay.trigger_screen_scan)
        self.hotkeys.clear_answers.connect(self.overlay.clear_answers)
        self.hotkeys.toggle_subtitles.connect(self.overlay.toggle_subtitles_tab)
        self.hotkeys.export_transcript.connect(self.export_transcript)
        self.overlay.export_requested.connect(self.export_transcript)

        self._register_hotkeys()
        self._start_audio_if_needed()

    def _register_hotkeys(self) -> None:
        hk = self.settings.get("hotkeys", {})
        self.hotkeys.update_hotkeys(
            str(hk.get("toggle_visibility", "ctrl+shift+g")),
            str(hk.get("screen_scan", "ctrl+shift+s")),
            str(hk.get("clear_answers", "ctrl+shift+c")),
            str(hk.get("toggle_subtitles", "ctrl+shift+t")),
            str(hk.get("export_transcript", "ctrl+shift+e")),
        )

    def _on_settings_changed(self, data: Dict[str, Any]) -> None:
        self.settings.update(data)
        save_settings(self.settings)
        self.overlay.apply_settings(self.settings)
        self._register_hotkeys()
        self._start_audio_if_needed()

    def _start_audio_if_needed(self) -> None:
        if self._audio is not None:
            self._audio.stop_listening()
            self._audio = None
        if not self.settings.get("subtitles_enabled", True):
            return
        if not self.settings.get("capture_mic", True) and not self.settings.get(
            "capture_system", False
        ):
            return
        loop_dev = self.settings.get("loopback_device")
        if loop_dev is not None:
            try:
                loop_dev = int(loop_dev)
            except (TypeError, ValueError):
                loop_dev = None
        self._audio = AudioListener(
            capture_mic=bool(self.settings.get("capture_mic", True)),
            capture_system=bool(self.settings.get("capture_system", False)),
            loopback_device=loop_dev,
            model_size=str(self.settings.get("whisper_model", "base")),
        )
        self._audio.subtitle_updated.connect(self._on_subtitle_line)
        self._audio.failed.connect(self._on_audio_failed)
        self._audio.start_listening()

    def _on_audio_failed(self, msg: str) -> None:
        logger.error("Audio: %s", msg)
        QMessageBox.warning(self.overlay, "GhostMind audio", msg)

    def _on_subtitle_line(self, line: str) -> None:
        self.overlay.push_subtitle_line(line)
        if "?" in line:
            self._meeting_timer.start(1600)

    # --- tray actions ---
    def _tray_show(self) -> None:
        if not self.overlay.isVisible():
            self.overlay.toggle_visibility_animated()

    def _tray_hide(self) -> None:
        if self.overlay.isVisible():
            self.overlay.toggle_visibility_animated()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.overlay.toggle_visibility_animated()

    def _tray_quit(self) -> None:
        self._tray.hide()
        self._app.quit()

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
        self.overlay.request_ai_answer(text, "meeting_audio")


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("GhostMind")
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    settings = load_settings()
    ctrl = GhostMindController(app, settings)

    def _sigint(*_args) -> None:
        logger.info("SIGINT — quitting")
        app.quit()

    signal.signal(signal.SIGINT, _sigint)
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(400)

    app.aboutToQuit.connect(ctrl.hotkeys.unregister_all)

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

    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
