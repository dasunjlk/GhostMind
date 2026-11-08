"""
In-overlay tabbed settings: General, Audio, Shortcuts, API, and About.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
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

from core import ai_engine
from core.ai_engine import (
    AVAILABLE_MODELS,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DETERMINISTIC_SEED,
    DETERMINISTIC_TEMPERATURE,
    _get_client,
)
from core.audio_listener import get_input_devices
from core.screen_reader import get_monitors
from ui.feedback_panel import FeedbackPanel
from utils import key_store
from version import (
    __app_name__,
    __author__,
    __copyright__,
    __description__,
    __github__,
    __version__,
)


class _ApiTestSignals(QObject):
    # (ok, message, discovered model IDs)
    finished = pyqtSignal(bool, str, list)


class SettingsPanel(QWidget):
    saved = pyqtSignal(dict)
    opacity_preview = pyqtSignal(float)
    close_requested = pyqtSignal()

    def __init__(self, initial: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self._data = dict(initial)
        self._custom_models: List[str] = []
        self._discovered_models: List[str] = []
        self._discovered_for: str = ""
        # Signature (base URL, effective key, model) of the last successful Check.
        self._checked_values: Optional[Tuple[str, str, str]] = None
        self._pending_check: Optional[Dict[str, Any]] = None
        self._pending_save: Optional[Dict[str, Any]] = None

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
        # v1.0: subtitles hidden (future-plan.md checklist); row kept for future.
        form_gen.setRowVisible(self._subtitles_startup, False)

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
        self._hk_ask = QLineEdit()

        form_keys.addRow("Toggle Visibility:", self._hk_vis)
        form_keys.addRow("Screen Scan (OCR):", self._hk_scan)
        form_keys.addRow("Clear Answers:", self._hk_clear)
        form_keys.addRow("Toggle Subtitles:", self._hk_sub)
        form_keys.addRow("Export Transcript:", self._hk_export)
        # v1.0: subtitles + transcript export hidden (future-plan.md checklist).
        form_keys.setRowVisible(self._hk_sub, False)
        form_keys.setRowVisible(self._hk_export, False)
        form_keys.addRow("Toggle Click-Through:", self._hk_click)
        form_keys.addRow("Focus Question Box:", self._hk_ask)

        # 4. API Tab
        tab_api = QWidget()
        form_api = QFormLayout(tab_api)
        form_api.setContentsMargins(10, 12, 10, 12)
        form_api.setSpacing(10)

        # Base URL selects the provider; there is deliberately no provider
        # dropdown. The model combo is editable: discovery fills it, but any
        # typed model ID is accepted and retained.
        self._api_base_url = QLineEdit()
        self._api_base_url.setPlaceholderText(DEFAULT_BASE_URL)
        self._api_base_url.setClearButtonEnabled(True)
        self._api_base_url.editingFinished.connect(self._on_base_url_edited)

        self._ai_model = QComboBox()
        self._ai_model.setEditable(True)
        self._ai_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._ai_model.setToolTip(
            "Pick a model loaded from the provider, or type its exact model ID."
        )
        self._populate_model_combo()

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("Paste key — saved to Windows Credential Manager")

        self._key_status = QLabel("")
        self._key_status.setWordWrap(True)
        self._key_status.setStyleSheet("color:#777777;font-size:11px;")

        self._clear_key_btn = QPushButton("Clear stored key")
        self._clear_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_key_btn.setStyleSheet(
            "QPushButton{background:#141414;color:#CC6666;border:1px solid #552222;padding:5px 10px;border-radius:4px;font-size:11px;}"
            "QPushButton:hover{background:#2A1414;color:#FF8888;border-color:#CC6666;}"
        )
        self._clear_key_btn.clicked.connect(self._on_clear_key)

        self._check_btn = QPushButton("Check & load models")
        self._check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._check_btn.setStyleSheet(
            "QPushButton{background:#162B1E;color:#00FF88;border:1px solid #00FF88;padding:6px 12px;border-radius:4px;}"
            "QPushButton:hover{background:#1E3E2B;}"
        )
        self._check_btn.clicked.connect(lambda: self._on_check_models())

        form_api.addRow("Base URL:", self._api_base_url)
        form_api.addRow("API Key:", self._api_key)
        form_api.addRow("Model:", self._ai_model)
        status_row = QHBoxLayout()
        status_row.addWidget(self._key_status, 1)
        status_row.addWidget(self._clear_key_btn)
        form_api.addRow("", status_row)
        form_api.addRow("", self._check_btn)
        self._api_tab = tab_api

        # 5. Feedback Tab (C13) — visible: praise, bugs, and ideas go to the
        # same privacy-safe channel as error reports.
        self._feedback_tab = FeedbackPanel()

        # 6. About Tab
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
        # C11: screen scanning ships inside the installer — acknowledge it.
        bundled_ocr = QLabel(
            "Bundled OCR: Tesseract (Apache License 2.0) — see TESSERACT-NOTICE.txt in the install folder."
        )
        bundled_ocr.setWordWrap(True)
        bundled_ocr.setStyleSheet("color:#888888;font-size:11px;")
        about_lay.addWidget(bundled_ocr)
        about_lay.addWidget(app_author)
        about_lay.addWidget(app_copy)
        about_lay.addSpacing(6)
        about_lay.addWidget(link_btn)
        about_lay.addStretch(1)

        # 6. Preferences Tab (appearance & future personalization options)
        tab_prefs = QWidget()
        form_prefs = QFormLayout(tab_prefs)
        form_prefs.setContentsMargins(10, 12, 10, 12)
        form_prefs.setSpacing(8)

        self._font_size = QSpinBox()
        self._font_size.setRange(9, 24)
        self._font_size.setSuffix(" pt")
        self._font_size.setValue(int(self._data.get("font_size", 13)))
        self._font_size.setToolTip("Base text size for answers, subtitles, and input (9-24)")
        form_prefs.addRow("Font size:", self._font_size)

        prefs_hint = QLabel("More appearance options coming in future updates.")
        prefs_hint.setStyleSheet("color:#666;font-size:11px;")
        form_prefs.addRow(prefs_hint)

        # Assemble Tabs
        self._tabs.addTab(tab_general, "General")
        self._tabs.addTab(tab_audio, "Audio")
        self._tabs.addTab(tab_keys, "Shortcuts")
        self._tabs.addTab(tab_api, "API")
        self._tabs.addTab(tab_prefs, "Preferences")
        self._tabs.addTab(self._feedback_tab, "Feedback")
        self._tabs.addTab(tab_about, "About")

        # v1.0: the Audio tab (capture / Whisper / session mode) is hidden for the
        # first release; its controls stay wired for re-enable (future-plan.md).
        self._tabs.setTabVisible(self._tabs.indexOf(tab_audio), False)

        # Bottom Buttons
        save_btn = QPushButton("Save")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            "QPushButton{background:#00FF88;color:#0A0A0A;border:none;padding:7px 18px;font-weight:bold;border-radius:4px;}"
            "QPushButton:hover{background:#33FFAA;}"
        )
        save_btn.clicked.connect(self._emit_save)
        self._save_btn = save_btn

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{background:#1A1A1A;color:#CCCCCC;border:1px solid #333333;padding:7px 14px;border-radius:4px;}"
            "QPushButton:hover{background:#252525;color:#FFFFFF;}"
        )
        close_btn.clicked.connect(lambda: self.close_requested.emit())

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
        self._api_base_url.textChanged.connect(self._invalidate_check)
        self._api_key.textChanged.connect(self._invalidate_check)
        self._ai_model.currentTextChanged.connect(self._invalidate_check)
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

    def set_click_through(self, on: bool) -> None:
        """Sync the combo when the header toggle changes click-through."""
        self._click_through.setCurrentText("on" if on else "off")

    def focus_api_tab(self) -> None:
        """Open the API tab and focus the key field (first-run CTA / tray)."""
        self._tabs.setCurrentWidget(self._api_tab)
        self._api_key.setFocus()

    def focus_feedback_tab(self) -> None:
        """Open the Feedback tab (tray 'Send feedback…')."""
        self._tabs.setCurrentWidget(self._feedback_tab)

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
        val_int = round(op * 100)
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

        # Preferences
        self._font_size.setValue(int(self._data.get("font_size", 13)))

        # Base URL selects the provider; it also decides which key slot and
        # model catalog are active.
        base_url = str(self._data.get("api_base_url") or DEFAULT_BASE_URL).strip()
        base_url = base_url or DEFAULT_BASE_URL
        if self._discovered_for and self._discovered_for.rstrip("/") != base_url.rstrip("/"):
            self._discovered_models = []
            self._discovered_for = ""
        self._api_base_url.setText(base_url)

        # AI Model (persisted custom IDs may not exist yet in a fresh combo)
        self._custom_models = list(self._data.get("custom_models") or [])
        self._populate_model_combo(self._discovered_models or None)
        chosen_model = str(self._data.get("ai_model", DEFAULT_MODEL))
        idx = self._ai_model.findData(chosen_model)
        if idx < 0 and chosen_model:
            # Model from another machine/import: keep it usable instead of silently
            # falling back to the default.
            self._ai_model.addItem(chosen_model, chosen_model)
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
        self._hk_ask.setText(str(hk.get("ask_question", "ctrl+shift+q")))

        # API key status (never render the key itself)
        self._refresh_key_status()
        self._api_key.clear()
        self._checked_values = None
        self._pending_check = None
        self._pending_save = None

    def collect_data(self) -> Dict[str, Any]:
        monitor_id = 1
        if self._monitor.currentData() is not None:
            monitor_id = int(self._monitor.currentData())

        loopback_id = self._loopback_device.currentData()

        model = self._selected_model()
        # Typed IDs (including discovered IDs) persist across restarts via
        # custom_models, matching the old "Add custom model" behaviour.
        known = {model_id for model_id, _label in AVAILABLE_MODELS}
        if model and model not in known and model not in self._custom_models:
            self._custom_models.append(model)

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
            "font_size": int(self._font_size.value()),
            "api_base_url": self._api_base_url.text().strip() or DEFAULT_BASE_URL,
            "ai_model": model,
            "custom_models": list(self._custom_models),
            "hotkeys": {
                "toggle_visibility": self._hk_vis.text().strip(),
                "screen_scan": self._hk_scan.text().strip(),
                "clear_answers": self._hk_clear.text().strip(),
                "toggle_subtitles": self._hk_sub.text().strip(),
                "export_transcript": self._hk_export.text().strip(),
                "toggle_click_through": self._hk_click.text().strip(),
                "ask_question": self._hk_ask.text().strip(),
            },
        }

    def _is_default_base_url(self) -> bool:
        raw = self._api_base_url.text().strip() or DEFAULT_BASE_URL
        return raw.rstrip("/") == DEFAULT_BASE_URL.rstrip("/")

    def _selected_model(self) -> str:
        """Return the selected item's model ID or the typed text."""
        text = self._ai_model.currentText().strip()
        if not text:
            return ""
        data = self._ai_model.currentData()
        index = self._ai_model.currentIndex()
        if (
            isinstance(data, str)
            and data.strip()
            and index >= 0
            and self._ai_model.itemText(index) == self._ai_model.currentText()
        ):
            return data.strip()
        return text

    def _populate_model_combo(self, models: Optional[List[str]] = None) -> None:
        """Rebuild the editable combo, keeping the current/typed model.

        `models` is a discovered provider catalog; when omitted, the built-in
        Groq list is used for the default URL and no static list is shown for
        custom providers.
        """
        current = self._selected_model()
        self._ai_model.blockSignals(True)
        self._ai_model.clear()
        if models is not None:
            unique = sorted({str(model_id) for model_id in models}, key=str.lower)
            entries = [(model_id, model_id) for model_id in unique]
        elif self._is_default_base_url():
            entries = list(AVAILABLE_MODELS)
        else:
            entries = []
        for model_id, label in entries:
            self._ai_model.addItem(label, model_id)
        for custom_id in self._custom_models:
            if self._ai_model.findData(custom_id) < 0:
                self._ai_model.addItem(f"{custom_id} (custom)", custom_id)
        if current and self._ai_model.findData(current) < 0:
            # Typed/unknown IDs always survive a repopulation.
            self._ai_model.addItem(current, current)
        if current:
            idx = self._ai_model.findData(current)
            if idx >= 0:
                self._ai_model.setCurrentIndex(idx)
            else:
                self._ai_model.setEditText(current)
        self._ai_model.blockSignals(False)

    def _invalidate_check(self, *_args: Any) -> None:
        self._checked_values = None

    def _on_base_url_edited(self) -> None:
        self._invalidate_check()
        raw = self._api_base_url.text().strip() or DEFAULT_BASE_URL
        if self._discovered_for and self._discovered_for.rstrip("/") != raw.rstrip("/"):
            self._discovered_models = []
            self._discovered_for = ""
            self._populate_model_combo()
        self._refresh_key_status()

    def _stored_key(self, base_url: str) -> str:
        host = ai_engine.host_for_base_url(base_url)
        if not host:
            return ""
        try:
            return key_store.load_key_for(host)
        except Exception:
            return ""

    def _refresh_key_status(self) -> None:
        raw = self._api_base_url.text().strip() or DEFAULT_BASE_URL
        host = ai_engine.host_for_base_url(raw)
        label = host or "this provider"
        stored = self._stored_key(raw)
        if stored:
            where = (
                "Windows Credential Manager"
                if key_store.is_keyring_available()
                else "config/settings.toml (plaintext fallback)"
            )
            self._key_status.setText(f"● Key stored for {label} in {where}")
            self._key_status.setStyleSheet("color:#00FF88;font-size:11px;")
            self._api_key.setPlaceholderText(
                "•••••••••••••••• (stored — leave blank to keep)"
            )
        else:
            self._key_status.setText(f"No key stored for {label}.")
            self._key_status.setStyleSheet("color:#777777;font-size:11px;")
            self._api_key.setPlaceholderText(
                f"Paste key for {label} — saved to Windows Credential Manager"
            )

    def _set_status(self, message: str, color: str) -> None:
        self._key_status.setText(message)
        self._key_status.setStyleSheet(f"color:{color};font-size:11px;")

    def _show_error(self, message: str) -> None:
        self._tabs.setCurrentWidget(self._api_tab)
        self._set_status(f"● {message}", "#FF5555")

    def _emit_save(self) -> None:
        d = self.collect_data()
        model = str(d.get("ai_model", "")).strip()
        if not model:
            self._tabs.setCurrentWidget(self._api_tab)
            self._show_error("Choose or type a model before saving.")
            self._ai_model.setFocus()
            return

        try:
            base_url = ai_engine.normalize_base_url(str(d.get("api_base_url", "")))
        except ValueError as e:
            self._tabs.setCurrentWidget(self._api_tab)
            self._show_error(str(e))
            self._api_base_url.setFocus()
            return

        # Persist the normalized URL (no trailing slash) in the settings.
        self._api_base_url.setText(base_url)
        d["api_base_url"] = base_url
        key = self._api_key.text().strip()
        signature = (base_url, key or self._stored_key(base_url), model)
        if self._checked_values == signature:
            self._commit_save(d, key)
            return

        # Check was skipped or its values changed: validate before saving.
        self._pending_check = None
        self._pending_save = {"data": d, "key": key, "signature": signature}
        self._set_status("● Checking key and model before saving…", "#FFAA00")
        self._check_btn.setEnabled(False)
        self._save_btn.setEnabled(False)

        def _work() -> None:
            ok, msg = ai_engine.validate_key_and_model(
                api_key=key, model_id=model, base_url=base_url
            )
            self._api_signals.finished.emit(ok, msg, [])

        threading.Thread(target=_work, daemon=True).start()

    def _commit_save(self, d: Dict[str, Any], key_text: str) -> None:
        base_url = str(d.get("api_base_url") or DEFAULT_BASE_URL)
        host = ai_engine.host_for_base_url(base_url) or "this provider"
        if key_text:
            try:
                backend = key_store.save_key_for(host, key_text)
            except Exception as e:
                reason = str(e).strip() or e.__class__.__name__
                self._tabs.setCurrentWidget(self._api_tab)
                self._show_error(f"Could not save key: {reason}")
                self._api_key.setFocus()
                return
            where = (
                "Windows Credential Manager"
                if backend == "keyring"
                else "config/settings.toml (plaintext fallback)"
            )
            self._set_status(f"● Key saved to {where} for {host}", "#00FF88")
            self._api_key.clear()
            self._api_key.setPlaceholderText(
                "•••••••••••••••• (stored — leave blank to keep)"
            )
        else:
            self._refresh_key_status()

        effective = key_text or self._stored_key(base_url)
        self._checked_values = (
            base_url,
            effective,
            str(d.get("ai_model", "")).strip(),
        )
        self.saved.emit(d)

    def _on_clear_key(self) -> None:
        raw = self._api_base_url.text().strip() or DEFAULT_BASE_URL
        host = ai_engine.host_for_base_url(raw)
        if not host:
            QMessageBox.warning(
                self, "Clear Stored Key", "Enter a valid Base URL first."
            )
            return
        confirm = QMessageBox.question(
            self,
            "Clear Stored Key",
            f"Remove the stored API key for {host} from this computer?\n"
            "AI answers will stop working until you enter a new key.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            key_store.clear_key_for(host)
        except Exception as e:
            QMessageBox.warning(self, "Key Storage Failed", str(e))
            return
        self._refresh_key_status()
        self._api_key.clear()
        self._checked_values = None

    def _on_check_models(self) -> None:
        """Validate URL -> key -> model, then load the provider's model list."""
        raw = self._api_base_url.text().strip()
        try:
            base_url = ai_engine.normalize_base_url(raw)
        except ValueError as e:
            self._show_error(str(e))
            return
        self._api_base_url.setText(base_url)

        model = self._selected_model()
        key = self._api_key.text().strip()
        self._pending_save = None
        self._pending_check = {"base_url": base_url, "key": key, "model": model}
        self._checked_values = None
        self._set_status("● Checking URL, key, and models…", "#FFAA00")
        self._check_btn.setEnabled(False)
        self._save_btn.setEnabled(False)

        def _work() -> None:
            ok, msg, models = ai_engine.discover_models(
                api_key=key, base_url=base_url, model_id=model or None
            )
            self._api_signals.finished.emit(ok, msg, list(models))

        threading.Thread(target=_work, daemon=True).start()

    def _show_api_result(self, ok: bool, msg: str, models: list) -> None:
        self._check_btn.setEnabled(True)
        self._save_btn.setEnabled(True)
        pending_save = self._pending_save
        pending_check = self._pending_check
        self._pending_save = None
        self._pending_check = None

        if pending_save is not None:
            if not ok:
                self._checked_values = None
                self._show_error(msg)
                return
            self._commit_save(pending_save["data"], pending_save["key"])
            return

        if not ok:
            self._checked_values = None
            self._show_error(msg)
            return

        self._set_status(f"● {msg}", "#00FF88")
        if models:
            self._discovered_models = [str(model) for model in models]
            self._discovered_for = (
                pending_check["base_url"] if pending_check else ""
            )
            self._populate_model_combo(self._discovered_models)
        if pending_check is not None and pending_check["model"]:
            effective = pending_check["key"] or self._stored_key(
                pending_check["base_url"]
            )
            self._checked_values = (
                pending_check["base_url"],
                effective,
                pending_check["model"],
            )

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
    """Synchronous API check against the default provider."""
    try:
        client = _get_client(DEFAULT_BASE_URL, api_key)
        client.chat.completions.create(
            model=DEFAULT_MODEL,
            max_tokens=16,
            temperature=DETERMINISTIC_TEMPERATURE,
            seed=DETERMINISTIC_SEED,
            messages=[{"role": "user", "content": "Reply with OK only."}],
        )
        on_done(True, "API key works.")
    except Exception as e:
        on_done(False, str(e))

