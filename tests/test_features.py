"""
Tests for newly added GhostMind features:
- Version metadata
- Audio resampling and device enumeration
- Window title and meeting app detection
- Settings panel tabs and data collection
- SubtitleBar summarize signal
"""
from __future__ import annotations

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

import version
from core.audio_listener import resample_to_16k, get_input_devices, find_loopback_device_index
from core.screen_reader import get_active_window_title, detect_meeting_app, get_screen_context
from ui.settings_panel import SettingsPanel
from ui.subtitle_bar import SubtitleBar


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestVersionMetadata:
    def test_version_constants(self):
        assert version.__version__ == "1.0.0"
        assert version.__app_name__ == "GhostMind"
        assert "Dasun" in version.__author__
        assert "dasunjlk/GhostMind" in version.__github__
        assert "© 2024-2026" in version.__copyright__


class TestModelConfiguration:
    def test_default_model_is_qwen38(self):
        from core.ai_engine import DEFAULT_MODEL, MODEL_ID
        assert DEFAULT_MODEL == "qwen/qwen3.8-27b"
        assert MODEL_ID == "qwen/qwen3.8-27b"

    def test_backup_models_available(self):
        from core.ai_engine import BACKUP_MODELS, AVAILABLE_MODELS
        assert "qwen/qwen3.6-27b" in BACKUP_MODELS
        assert "openai/gpt-oss-120b" in BACKUP_MODELS
        assert "openai/gpt-oss-20b" in BACKUP_MODELS

        model_ids = [mid for mid, _ in AVAILABLE_MODELS]
        assert "qwen/qwen3.8-27b" in model_ids
        assert "qwen/qwen3.6-27b" in model_ids
        assert "openai/gpt-oss-120b" in model_ids
        assert "openai/gpt-oss-20b" in model_ids



class TestAudioResampling:
    def test_resample_identical_rate(self):
        audio = np.ones(16000, dtype=np.float32)
        res = resample_to_16k(audio, 16000)
        assert len(res) == 16000
        assert np.array_equal(audio, res)

    def test_resample_48k_to_16k(self):
        audio = np.ones(48000, dtype=np.float32)
        res = resample_to_16k(audio, 48000)
        assert len(res) == 16000

    def test_resample_44k_to_16k(self):
        audio = np.ones(44100, dtype=np.float32)
        res = resample_to_16k(audio, 44100)
        assert len(res) == 16000

    def test_resample_empty_audio(self):
        audio = np.empty(0, dtype=np.float32)
        res = resample_to_16k(audio, 48000)
        assert len(res) == 0


class TestAudioDevices:
    def test_get_input_devices(self):
        devs = get_input_devices()
        assert isinstance(devs, list)
        for d in devs:
            assert "id" in d
            assert "name" in d
            assert "channels" in d
            assert d["channels"] > 0

    def test_find_loopback_device_returns_int_or_none(self):
        idx = find_loopback_device_index()
        assert idx is None or isinstance(idx, int)


class TestScreenContext:
    def test_active_window_title_returns_string(self):
        title = get_active_window_title()
        assert isinstance(title, str)

    def test_detect_meeting_app_returns_optional_string(self):
        app = detect_meeting_app()
        assert app is None or isinstance(app, str)


class TestSettingsPanelTabs:
    def test_settings_tabs_initialized(self, qapp):
        initial = {
            "monitor_id": 1,
            "scan_mode": "manual",
            "auto_scan_interval_sec": 30,
            "opacity": 0.85,
            "click_through": False,
            "subtitles_enabled": True,
            "session_type": "meeting",
            "capture_mic": True,
            "capture_system": True,
            "ai_model": "qwen/qwen3.8-27b",
            "whisper_model": "base",
            "loopback_device": None,
            "hotkeys": {
                "toggle_visibility": "ctrl+shift+g",
                "screen_scan": "ctrl+shift+s",
                "clear_answers": "ctrl+shift+c",
                "toggle_subtitles": "ctrl+shift+t",
                "export_transcript": "ctrl+shift+e",
                "toggle_click_through": "ctrl+shift+x",
            },
        }
        panel = SettingsPanel(initial)
        assert panel._tabs.count() == 5
        tab_names = [panel._tabs.tabText(i) for i in range(5)]
        assert tab_names == ["General", "Audio", "Shortcuts", "AI & API", "About"]

        # Test data collection
        collected = panel.collect_data()
        assert collected["opacity"] == pytest.approx(0.85, 0.02)
        assert collected["session_type"] == "meeting"
        assert collected["capture_system"] is True
        assert collected["ai_model"] == "qwen/qwen3.8-27b"
        assert "hotkeys" in collected



class TestSubtitleBarFeatures:
    def test_subtitle_bar_signals(self, qapp):
        bar = SubtitleBar()
        assert hasattr(bar, "save_requested")
        assert hasattr(bar, "summarize_requested")

        # Test line appending and speaker formatting
        bar.append_line("Mic: Testing microphone")
        bar.append_line("Lecturer: This is an important theorem?")
        bar.append_line("System: Someone is speaking in the meeting")
        plain = bar._view.toPlainText()
        assert "Testing microphone" in plain
        assert "important theorem" in plain
        assert "Someone is speaking" in plain


class TestWorkerSafety:
    def test_is_worker_active_none(self):
        from ui.overlay_window import _is_worker_active
        assert _is_worker_active(None) is False

    def test_is_worker_active_deleted(self, qapp):
        from PyQt6.QtCore import QThread
        from ui.overlay_window import _is_worker_active
        worker = QThread()
        # Delete underlying C++ object
        worker.deleteLater()
        qapp.processEvents()
        # Should return False safely without raising RuntimeError
        assert _is_worker_active(worker) is False


