"""Tests for the no-microphone warning badge on the header mic toggle."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

import core.audio_listener as audio_listener
from core.audio_listener import has_microphone
from tests.test_window_geometry import BASE_SETTINGS
from ui.overlay_window import OverlayWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def overlay(qapp):
    win = OverlayWindow(dict(BASE_SETTINGS), Path("."))
    win.show()
    yield win
    win.close()


class TestHasMicrophone:
    def test_true_when_input_devices_exist(self, monkeypatch):
        monkeypatch.setattr(
            audio_listener,
            "get_input_devices",
            lambda: [{"id": 0, "name": "Mic"}],
        )
        assert has_microphone() is True

    def test_false_when_no_input_devices(self, monkeypatch):
        monkeypatch.setattr(audio_listener, "get_input_devices", list)
        assert has_microphone() is False

    def test_false_when_detection_raises(self, monkeypatch):
        def _boom():
            raise OSError("no audio host API")

        monkeypatch.setattr(audio_listener, "get_input_devices", _boom)
        assert has_microphone() is False, "detection failure counts as 'no mic'"


class TestMicBadge:
    def test_default_assumes_device_present(self, overlay):
        # Tests/CI run without probing; badge must NOT show by default.
        assert overlay._has_microphone is None
        assert overlay._mic_toggle._has_device is True
        assert "no microphone" not in overlay._mic_toggle.toolTip()

    def test_no_mic_sets_badge_state_and_tooltip(self, overlay):
        overlay.set_microphone_available(False)
        assert overlay._mic_toggle._has_device is False
        assert "no microphone detected" in overlay._mic_toggle.toolTip()

    def test_mic_present_clears_badge(self, overlay):
        overlay.set_microphone_available(False)
        overlay.set_microphone_available(True)
        assert overlay._mic_toggle._has_device is True
        assert "no microphone" not in overlay._mic_toggle.toolTip()

    def test_speaker_icon_unaffected(self, overlay):
        overlay.set_microphone_available(False)
        assert overlay._sys_toggle._has_device is True, "speaker has no such badge"
