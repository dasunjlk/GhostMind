"""
GhostMind — stealth PyQt6 overlay entry point.
"""
from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import toml
from dotenv import load_dotenv
from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

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


class GhostMindController(QObject):
    """Owns hotkeys, audio thread, and settings persistence."""

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

        self.overlay.settings_changed.connect(self._on_settings_changed)

        self.hotkeys.toggle_visibility.connect(self.overlay.toggle_visibility_animated)
        self.hotkeys.trigger_screen_scan.connect(self.overlay.trigger_screen_scan)
        self.hotkeys.clear_answers.connect(self.overlay.clear_answers)
        self.hotkeys.toggle_subtitles.connect(self.overlay.toggle_subtitles_tab)

        self._register_hotkeys()
        self._start_audio_if_needed()

    def _register_hotkeys(self) -> None:
        hk = self.settings.get("hotkeys", {})
        self.hotkeys.update_hotkeys(
            str(hk.get("toggle_visibility", "ctrl+shift+g")),
            str(hk.get("screen_scan", "ctrl+shift+s")),
            str(hk.get("clear_answers", "ctrl+shift+c")),
            str(hk.get("toggle_subtitles", "ctrl+shift+t")),
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
