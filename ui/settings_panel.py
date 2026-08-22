"""
In-overlay settings: monitors, scan mode, opacity, hotkeys, API test, save to TOML.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.screen_reader import get_monitors


class _ApiTestSignals(QObject):
    finished = pyqtSignal(bool, str)


class SettingsPanel(QWidget):
    saved = pyqtSignal(dict)

    def __init__(self, initial: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self._data = dict(initial)

        title = QLabel("Settings")
        title.setStyleSheet("color:#00FF88;font-weight:bold;font-size:14px;")

        self._monitor = QComboBox()
        self._reload_monitors()

        self._scan_mode = QComboBox()
        self._scan_mode.addItems(["manual", "auto"])
        self._scan_interval = QSpinBox()
        self._scan_interval.setRange(5, 600)
        self._scan_interval.setSuffix(" sec")

        self._opacity = QSlider(Qt.Orientation.Horizontal)
        self._opacity.setRange(50, 100)
        self._opacity_label = QLabel()

        self._hk_vis = QLineEdit()
        self._hk_scan = QLineEdit()
        self._hk_clear = QLineEdit()
        self._hk_sub = QLineEdit()
        self._hk_export = QLineEdit()

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)

        self._click_through = QComboBox()
        self._click_through.addItems(["off", "on"])

        self._cap_mic = QComboBox()
        self._cap_mic.addItems(["yes", "no"])
        self._cap_sys = QComboBox()
        self._cap_sys.addItems(["no", "yes"])

        self._whisper = QComboBox()
        self._whisper.addItems(["tiny", "base", "small", "medium"])

        self._subtitles = QComboBox()
        self._subtitles.addItems(["yes", "no"])

        self._api_signals = _ApiTestSignals(self)
        self._api_signals.finished.connect(self._show_api_result)

        form = QFormLayout()
        form.addRow("Monitor", self._monitor)
        form.addRow("Scan mode", self._scan_mode)
        form.addRow("Auto interval", self._scan_interval)
        form.addRow("Opacity", self._opacity_label)
        form.addRow("", self._opacity)
        form.addRow("Click-through", self._click_through)
        form.addRow("Capture mic", self._cap_mic)
        form.addRow("Capture system audio", self._cap_sys)
        form.addRow("Whisper model", self._whisper)
        form.addRow("Subtitles on startup", self._subtitles)
        form.addRow("Toggle visibility", self._hk_vis)
        form.addRow("Screen scan", self._hk_scan)
        form.addRow("Clear answers", self._hk_clear)
        form.addRow("Toggle subtitles", self._hk_sub)
        form.addRow("Export transcript", self._hk_export)
        form.addRow("API key", self._api_key)

        test_btn = QPushButton("Test API key")
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.setStyleSheet(
            "QPushButton{background:#1A1A1A;color:#00FF88;border:none;padding:6px 12px;}"
            "QPushButton:hover{background:#252525;}"
        )
        test_btn.clicked.connect(self._on_test_api)

        save_btn = QPushButton("Save")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            "QPushButton{background:#00FF88;color:#0A0A0A;border:none;padding:8px 16px;font-weight:bold;}"
            "QPushButton:hover{background:#33FFAA;}"
        )
        save_btn.clicked.connect(self._emit_save)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{background:#1A1A1A;color:#E0E0E0;border:none;padding:6px 12px;}"
            "QPushButton:hover{background:#2A2A2A;}"
        )
        close_btn.clicked.connect(self.hide)

        row = QHBoxLayout()
        row.addWidget(test_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        row.addWidget(save_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(title)
        root.addLayout(form)
        root.addLayout(row)

        self._opacity.valueChanged.connect(self._update_opacity_label)
        self.apply_data(self._data)

    def _update_opacity_label(self, v: int) -> None:
        self._opacity_label.setText(f"{v / 100.0:.2f}")

    def _reload_monitors(self) -> None:
        self._monitor.clear()
        try:
            mons: List[dict] = get_monitors()
        except Exception:
            mons = []
        for m in mons:
            label = f"{m['name']} ({m['width']}×{m['height']}) @ ({m['x']},{m['y']})"
            self._monitor.addItem(label, m["id"])

    def apply_data(self, data: Dict[str, Any]) -> None:
        self._data = dict(data)
        mid = int(self._data.get("monitor_id", 1))
        for i in range(self._monitor.count()):
            if int(self._monitor.itemData(i)) == mid:
                self._monitor.setCurrentIndex(i)
                break
        mode = str(self._data.get("scan_mode", "manual"))
        self._scan_mode.setCurrentText(mode)
        self._scan_interval.setValue(int(self._data.get("auto_scan_interval_sec", 30)))
        op = float(self._data.get("opacity", 0.92))
        self._opacity.setValue(int(round(op * 100)))
        self._update_opacity_label(self._opacity.value())

        hk = self._data.get("hotkeys", {})
        self._hk_vis.setText(str(hk.get("toggle_visibility", "ctrl+shift+g")))
        self._hk_scan.setText(str(hk.get("screen_scan", "ctrl+shift+s")))
        self._hk_clear.setText(str(hk.get("clear_answers", "ctrl+shift+c")))
        self._hk_sub.setText(str(hk.get("toggle_subtitles", "ctrl+shift+t")))
        self._hk_export.setText(str(hk.get("export_transcript", "ctrl+shift+e")))

        key = os.environ.get("GROQ_API_KEY", "")
        if key:
            self._api_key.setPlaceholderText("•••• (loaded from .env)")
        self._api_key.clear()

        self._click_through.setCurrentText("on" if self._data.get("click_through") else "off")
        self._cap_mic.setCurrentText("yes" if self._data.get("capture_mic", True) else "no")
        self._cap_sys.setCurrentText("yes" if self._data.get("capture_system") else "no")
        self._whisper.setCurrentText(str(self._data.get("whisper_model", "base")))
        self._subtitles.setCurrentText("yes" if self._data.get("subtitles_enabled", True) else "no")

    def collect_data(self) -> Dict[str, Any]:
        monitor_id = 1
        if self._monitor.currentData() is not None:
            monitor_id = int(self._monitor.currentData())
        return {
            "monitor_id": monitor_id,
            "scan_mode": self._scan_mode.currentText(),
            "auto_scan_interval_sec": int(self._scan_interval.value()),
            "opacity": self._opacity.value() / 100.0,
            "click_through": self._click_through.currentText() == "on",
            "capture_mic": self._cap_mic.currentText() == "yes",
            "capture_system": self._cap_sys.currentText() == "yes",
            "whisper_model": self._whisper.currentText(),
            "subtitles_enabled": self._subtitles.currentText() == "yes",
            "hotkeys": {
                "toggle_visibility": self._hk_vis.text().strip(),
                "screen_scan": self._hk_scan.text().strip(),
                "clear_answers": self._hk_clear.text().strip(),
                "toggle_subtitles": self._hk_sub.text().strip(),
                "export_transcript": self._hk_export.text().strip(),
            },
        }

    def _emit_save(self) -> None:
        d = self.collect_data()
        k = self._api_key.text().strip()
        if k:
            os.environ["GROQ_API_KEY"] = k
        self.saved.emit(d)

    def _on_test_api(self) -> None:
        k = self._api_key.text().strip() or os.environ.get("GROQ_API_KEY", "")
        if not k:
            QMessageBox.warning(self, "API key", "Enter an API key or set GROQ_API_KEY in .env")
            return

        def _work() -> None:
            try:
                from groq import Groq

                client = Groq(api_key=k)
                client.chat.completions.create(
                    model="llama-3.1-70b-versatile",
                    max_tokens=16,
                    messages=[{"role": "user", "content": "Reply with OK only."}],
                )
                self._api_signals.finished.emit(True, "API key works.")
            except Exception as e:
                self._api_signals.finished.emit(False, str(e))

        threading.Thread(target=_work, daemon=True).start()

    def _show_api_result(self, ok: bool, msg: str) -> None:
        if ok:
            QMessageBox.information(self, "API", msg)
        else:
            QMessageBox.warning(self, "API", msg)


def run_api_self_test(api_key: str, on_done: Callable[[bool, str], None]) -> None:
    """Synchronous API check (prefer threaded _on_test_api in SettingsPanel)."""
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with OK only."}],
        )
        on_done(True, "API key works.")
    except Exception as e:
        on_done(False, str(e))
