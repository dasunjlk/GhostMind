"""
In-overlay tabbed settings: General, Audio, Shortcuts, AI & API, and About.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.ai_engine import AVAILABLE_MODELS, DEFAULT_MODEL
from core.audio_listener import get_input_devices
from core.screen_reader import get_monitors
from version import __app_name__, __author__, __copyright__, __description__, __github__, __version__



class _ApiTestSignals(QObject):
    finished = pyqtSignal(bool, str)


class SettingsPanel(QWidget):
    saved = pyqtSignal(dict)
    opacity_preview = pyqtSignal(float)

    def __init__(self, initial: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self._data = dict(initial)

        # Header Title
        title = QLabel("Settings")
        title.setStyleSheet("color:#00FF88;font-weight:bold;font-size:15px;margin-bottom:4px;")

        # Tab Widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #1E3A2B; background: #0E0E0E; border-radius: 6px; padding: 4px; }"
            "QTabBar::tab { color:#888; padding:7px 12px; background:#141414; border-top-left-radius:4px; border-top-right-radius:4px; margin-right:2px; font-size:11px; }"
            "QTabBar::tab:selected { color:#00FF88; background:#152B1E; border-bottom:2px solid #00FF88; font-weight:bold; }"
            "QTabBar::tab:hover { color:#E0E0E0; background:#202020; }"
        )

        # 1. General Tab
        tab_general = QWidget()
        form_gen = QFormLayout(tab_general)
        form_gen.setContentsMargins(10, 12, 10, 12)
        form_gen.setSpacing(10)

        self._monitor = QComboBox()
        self._reload_monitors()

        self._scan_mode = QComboBox()
        self._scan_mode.addItems(["manual", "auto"])

        self._scan_interval = QSpinBox()
        self._scan_interval.setRange(5, 600)
        self._scan_interval.setSuffix(" sec")

        self._opacity = QSlider(Qt.Orientation.Horizontal)
        self._opacity.setRange(20, 100)
        self._opacity_label = QLabel("92%")
        self._opacity_label.setStyleSheet("color:#00FF88;font-weight:bold;")

        self._click_through = QComboBox()
        self._click_through.addItems(["off", "on"])

        self._subtitles_startup = QComboBox()
        self._subtitles_startup.addItems(["yes", "no"])

        form_gen.addRow("Monitor:", self._monitor)
        form_gen.addRow("Scan Mode:", self._scan_mode)
        form_gen.addRow("Auto Interval:", self._scan_interval)
        
        op_row = QHBoxLayout()
        op_row.addWidget(self._opacity, 1)
        op_row.addWidget(self._opacity_label)
        form_gen.addRow("Opacity:", op_row)
        
        form_gen.addRow("Click-Through:", self._click_through)
        form_gen.addRow("Subtitles on Startup:", self._subtitles_startup)

        # 2. Audio Tab
        tab_audio = QWidget()
        form_aud = QFormLayout(tab_audio)
        form_aud.setContentsMargins(10, 12, 10, 12)
        form_aud.setSpacing(10)

        self._session_type = QComboBox()
        self._session_type.addItem("Meeting / Discussion", "meeting")
        self._session_type.addItem("Lecture / Class (Notes)", "lecture")

        self._cap_mic = QComboBox()
        self._cap_mic.addItems(["yes", "no"])

        self._cap_sys = QComboBox()
        self._cap_sys.addItems(["yes", "no"])

        self._loopback_device = QComboBox()
        self._reload_audio_devices()

        self._whisper = QComboBox()
        self._whisper.addItems(["tiny", "base", "small", "medium"])

        form_aud.addRow("Audio Mode:", self._session_type)
        form_aud.addRow("Capture Mic:", self._cap_mic)
        form_aud.addRow("Capture System Audio:", self._cap_sys)
        form_aud.addRow("System/Loopback Device:", self._loopback_device)
        form_aud.addRow("Whisper Model:", self._whisper)

        # 3. Shortcuts Tab
        tab_keys = QWidget()
        form_keys = QFormLayout(tab_keys)
        form_keys.setContentsMargins(10, 12, 10, 12)
        form_keys.setSpacing(8)

        self._hk_vis = QLineEdit()
        self._hk_scan = QLineEdit()
        self._hk_clear = QLineEdit()
        self._hk_sub = QLineEdit()
        self._hk_export = QLineEdit()
        self._hk_click = QLineEdit()

        form_keys.addRow("Toggle Visibility:", self._hk_vis)
        form_keys.addRow("Screen Scan (OCR):", self._hk_scan)
        form_keys.addRow("Clear Answers:", self._hk_clear)
        form_keys.addRow("Toggle Subtitles:", self._hk_sub)
        form_keys.addRow("Export Transcript:", self._hk_export)
        form_keys.addRow("Toggle Click-Through:", self._hk_click)

        # 4. AI & API Tab
        tab_api = QWidget()
        form_api = QFormLayout(tab_api)
        form_api.setContentsMargins(10, 12, 10, 12)
        form_api.setSpacing(10)

        self._ai_model = QComboBox()
        for model_id, label in AVAILABLE_MODELS:
            self._ai_model.addItem(label, model_id)


        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)

        test_btn = QPushButton("Test API Key")
        test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        test_btn.setStyleSheet(
            "QPushButton{background:#162B1E;color:#00FF88;border:1px solid #00FF88;padding:6px 12px;border-radius:4px;}"
            "QPushButton:hover{background:#1E3E2B;}"
        )
        test_btn.clicked.connect(self._on_test_api)

        form_api.addRow("AI Model:", self._ai_model)
        form_api.addRow("Groq API Key:", self._api_key)
        form_api.addRow("", test_btn)

        # 5. About Tab
        tab_about = QWidget()
        about_lay = QVBoxLayout(tab_about)
        about_lay.setContentsMargins(12, 14, 12, 14)
        about_lay.setSpacing(8)

        app_title = QLabel(f"{__app_name__} v{__version__}")
        app_title.setStyleSheet("color:#00FF88;font-size:16px;font-weight:bold;")
        
        app_desc = QLabel(__description__)
        app_desc.setStyleSheet("color:#AAAAAA;font-size:12px;")

        app_author = QLabel(f"Author: {__author__}")
        app_author.setStyleSheet("color:#CCCCCC;font-size:11px;")

        app_copy = QLabel(__copyright__)
        app_copy.setStyleSheet("color:#888888;font-size:11px;")

        # GitHub Repo Link
        link_btn = QPushButton("View GitHub Repository ↗")
        link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        link_btn.setStyleSheet(
            "QPushButton{background:#1A1A1A;color:#00FF88;border:1px solid #333333;padding:8px 12px;border-radius:4px;text-align:left;}"
            "QPushButton:hover{background:#222222;border-color:#00FF88;}"
        )
        link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(__github__)))

        about_lay.addWidget(app_title)
        about_lay.addWidget(app_desc)
        about_lay.addSpacing(4)
        about_lay.addWidget(app_author)
        about_lay.addWidget(app_copy)
        about_lay.addSpacing(6)
        about_lay.addWidget(link_btn)
        about_lay.addStretch(1)

        # Assemble Tabs
        self._tabs.addTab(tab_general, "General")
        self._tabs.addTab(tab_audio, "Audio")
        self._tabs.addTab(tab_keys, "Shortcuts")
        self._tabs.addTab(tab_api, "AI & API")
        self._tabs.addTab(tab_about, "About")

        # Bottom Buttons
        save_btn = QPushButton("Save")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            "QPushButton{background:#00FF88;color:#0A0A0A;border:none;padding:7px 18px;font-weight:bold;border-radius:4px;}"
            "QPushButton:hover{background:#33FFAA;}"
        )
        save_btn.clicked.connect(self._emit_save)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{background:#1A1A1A;color:#CCCCCC;border:1px solid #333333;padding:7px 14px;border-radius:4px;}"
            "QPushButton:hover{background:#252525;color:#FFFFFF;}"
        )
        close_btn.clicked.connect(self.hide)

        import_btn = QPushButton("Import")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.setStyleSheet(
            "QPushButton{background:#141414;color:#AAAAAA;border:1px solid #282828;padding:6px 12px;border-radius:4px;}"
            "QPushButton:hover{background:#202020;color:#FFFFFF;}"
        )
        import_btn.clicked.connect(self._on_import)

        export_btn = QPushButton("Export")
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.setStyleSheet(
            "QPushButton{background:#141414;color:#AAAAAA;border:1px solid #282828;padding:6px 12px;border-radius:4px;}"
            "QPushButton:hover{background:#202020;color:#FFFFFF;}"
        )
        export_btn.clicked.connect(self._on_export)

        btn_row = QHBoxLayout()
        btn_row.addWidget(import_btn)
        btn_row.addWidget(export_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        btn_row.addWidget(save_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.addWidget(title)
        root.addWidget(self._tabs, 1)
        root.addLayout(btn_row)

        self._api_signals = _ApiTestSignals(self)
        self._api_signals.finished.connect(self._show_api_result)

        self._opacity.valueChanged.connect(self._on_opacity_slider_changed)
        self.apply_data(self._data)

    def _on_opacity_slider_changed(self, v: int) -> None:
        val = v / 100.0
        self._opacity_label.setText(f"{int(v)}%")
        self.opacity_preview.emit(val)

    def _reload_monitors(self) -> None:
        self._monitor.clear()
        try:
            mons: List[dict] = get_monitors()
        except Exception:
            mons = []
        for m in mons:
            label = f"{m['name']} ({m['width']}×{m['height']})"
            self._monitor.addItem(label, m["id"])

    def _reload_audio_devices(self) -> None:
        self._loopback_device.clear()
        self._loopback_device.addItem("Default / Auto Loopback", None)
        try:
            devs = get_input_devices()
            for d in devs:
                self._loopback_device.addItem(d["name"], d["id"])
        except Exception:
            pass

    def apply_data(self, data: Dict[str, Any]) -> None:
        self._data = dict(data)
        
        # Monitor
        mid = int(self._data.get("monitor_id", 1))
        for i in range(self._monitor.count()):
            if int(self._monitor.itemData(i) or -1) == mid:
                self._monitor.setCurrentIndex(i)
                break
                
        # Scan mode & interval
        mode = str(self._data.get("scan_mode", "manual"))
        self._scan_mode.setCurrentText(mode)
        self._scan_interval.setValue(int(self._data.get("auto_scan_interval_sec", 30)))
        
        # Opacity
        op = float(self._data.get("opacity", 0.92))
        val_int = int(round(op * 100))
        self._opacity.setValue(max(20, min(100, val_int)))
        self._opacity_label.setText(f"{val_int}%")

        # Click-through & Subtitles
        self._click_through.setCurrentText("on" if self._data.get("click_through") else "off")
        self._subtitles_startup.setCurrentText("yes" if self._data.get("subtitles_enabled", True) else "no")

        # Audio
        st = str(self._data.get("session_type", "meeting"))
        idx = self._session_type.findData(st)
        if idx >= 0:
            self._session_type.setCurrentIndex(idx)
        self._cap_mic.setCurrentText("yes" if self._data.get("capture_mic", True) else "no")
        self._cap_sys.setCurrentText("yes" if self._data.get("capture_system", True) else "no")
        
        # Loopback device
        lb_dev = self._data.get("loopback_device")
        for i in range(self._loopback_device.count()):
            if self._loopback_device.itemData(i) == lb_dev:
                self._loopback_device.setCurrentIndex(i)
                break
                
        self._whisper.setCurrentText(str(self._data.get("whisper_model", "base")))

        # AI Model
        chosen_model = str(self._data.get("ai_model", DEFAULT_MODEL))
        idx = self._ai_model.findData(chosen_model)
        if idx >= 0:
            self._ai_model.setCurrentIndex(idx)

        # Hotkeys
        hk = self._data.get("hotkeys", {})
        self._hk_vis.setText(str(hk.get("toggle_visibility", "ctrl+shift+g")))
        self._hk_scan.setText(str(hk.get("screen_scan", "ctrl+shift+s")))
        self._hk_clear.setText(str(hk.get("clear_answers", "ctrl+shift+c")))
        self._hk_sub.setText(str(hk.get("toggle_subtitles", "ctrl+shift+t")))
        self._hk_export.setText(str(hk.get("export_transcript", "ctrl+shift+e")))
        self._hk_click.setText(str(hk.get("toggle_click_through", "ctrl+shift+x")))

        # API Key
        key = os.environ.get("GROQ_API_KEY", "")
        if key:
            self._api_key.setPlaceholderText("•••••••••••••••• (Active from environment)")
        self._api_key.clear()

    def collect_data(self) -> Dict[str, Any]:
        monitor_id = 1
        if self._monitor.currentData() is not None:
            monitor_id = int(self._monitor.currentData())

        loopback_id = self._loopback_device.currentData()

        return {
            "monitor_id": monitor_id,
            "scan_mode": self._scan_mode.currentText(),
            "auto_scan_interval_sec": int(self._scan_interval.value()),
            "opacity": self._opacity.value() / 100.0,
            "click_through": self._click_through.currentText() == "on",
            "subtitles_enabled": self._subtitles_startup.currentText() == "yes",
            "session_type": self._session_type.currentData() or "meeting",
            "capture_mic": self._cap_mic.currentText() == "yes",
            "capture_system": self._cap_sys.currentText() == "yes",
            "loopback_device": loopback_id,
            "whisper_model": self._whisper.currentText(),
            "ai_model": self._ai_model.currentData() or DEFAULT_MODEL,
            "hotkeys": {
                "toggle_visibility": self._hk_vis.text().strip(),
                "screen_scan": self._hk_scan.text().strip(),
                "clear_answers": self._hk_clear.text().strip(),
                "toggle_subtitles": self._hk_sub.text().strip(),
                "export_transcript": self._hk_export.text().strip(),
                "toggle_click_through": self._hk_click.text().strip(),
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
            QMessageBox.warning(self, "API Key Required", "Enter an API key or set GROQ_API_KEY in .env")
            return

        model = self._ai_model.currentData() or DEFAULT_MODEL


        def _work() -> None:
            try:
                from groq import Groq

                client = Groq(api_key=k)
                client.chat.completions.create(
                    model=model,
                    max_tokens=16,
                    messages=[{"role": "user", "content": "Reply with OK only."}],
                )
                self._api_signals.finished.emit(True, f"Groq API connected successfully using {model}!")
            except Exception as e:
                self._api_signals.finished.emit(False, f"API test failed:\n{e}")

        threading.Thread(target=_work, daemon=True).start()

    def _show_api_result(self, ok: bool, msg: str) -> None:
        if ok:
            QMessageBox.information(self, "API Status", msg)
        else:
            QMessageBox.warning(self, "API Status", msg)

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Settings", "", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            from utils.config_io import import_settings

            data = import_settings(path)
            if data is None:
                QMessageBox.warning(self, "Import Failed", "Could not read settings file.")
                return
            self.apply_data(data)
            QMessageBox.information(self, "Imported", "Settings loaded. Click Save to apply.")
        except Exception as e:
            QMessageBox.warning(self, "Import Failed", str(e))

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Settings", "ghostmind_settings.json",
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            from utils.config_io import export_settings

            data = self.collect_data()
            export_settings(data, path)
            QMessageBox.information(self, "Exported", f"Settings saved to {Path(path).name}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))


def run_api_self_test(api_key: str, on_done: Callable[[bool, str], None]) -> None:
    """Synchronous API check."""
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        client.chat.completions.create(
            model=DEFAULT_MODEL,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with OK only."}],
        )
        on_done(True, "API key works.")
    except Exception as e:
        on_done(False, str(e))

