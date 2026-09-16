"""Tests for the header quick-capture toggles (mic / system audio, Zoom-style)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from tests.test_window_geometry import BASE_SETTINGS
from ui.overlay_window import OverlayWindow, _CaptureIconWidget


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


def _click(widget) -> None:
    QTest.mouseClick(
        widget, Qt.MouseButton.LeftButton, pos=QPoint(widget.width() // 2, widget.height() // 2)
    )


class TestCaptureIconWidget:
    def test_initial_states(self, qapp):
        mic = _CaptureIconWidget("mic", True, "Microphone capture")
        spk = _CaptureIconWidget("speaker", False, "System audio capture")
        assert mic.is_on() and not spk.is_on()

    def test_click_toggles_and_emits(self, qapp):
        w = _CaptureIconWidget("mic", False, "Mic")
        seen: list = []
        w.toggled.connect(seen.append)
        _click(w)
        assert w.is_on() and seen == [True]
        _click(w)
        assert not w.is_on() and seen == [True, False]

    def test_set_on_does_not_emit(self, qapp):
        w = _CaptureIconWidget("speaker", True, "Sys")
        seen: list = []
        w.toggled.connect(seen.append)
        w.set_on(False)
        assert not w.is_on() and seen == [], "set_on is a programmatic sync, not a click"


class TestQuickTogglesSync:
    def test_defaults_match_settings(self, overlay):
        assert overlay._mic_toggle.is_on() == bool(
            overlay._settings.get("capture_mic", True)
        )
        assert overlay._sys_toggle.is_on() == bool(
            overlay._settings.get("capture_system", True)
        )

    def test_toggling_mic_only_changes_capture_mic(self, overlay):
        """BASE_SETTINGS starts both captures off; one click flips only mic."""
        assert not overlay._mic_toggle.is_on() and not overlay._sys_toggle.is_on()
        QTest.mouseClick(overlay._mic_toggle, Qt.MouseButton.LeftButton)
        assert overlay._settings["capture_mic"] is True
        assert overlay._settings["capture_system"] is False, "system toggle untouched"

    def test_both_on_then_system_off(self, overlay):
        """Both sources can run together; disabling one keeps the other."""
        QTest.mouseClick(overlay._mic_toggle, Qt.MouseButton.LeftButton)
        QTest.mouseClick(overlay._sys_toggle, Qt.MouseButton.LeftButton)
        assert (
            overlay._settings["capture_mic"] is True
            and overlay._settings["capture_system"] is True
        ), "both enabled simultaneously"
        QTest.mouseClick(overlay._sys_toggle, Qt.MouseButton.LeftButton)
        assert (
            overlay._settings["capture_mic"] is True
            and overlay._settings["capture_system"] is False
        ), "mic stays on while system is disabled"
        QTest.mouseClick(overlay._mic_toggle, Qt.MouseButton.LeftButton)
        assert (
            overlay._settings["capture_mic"] is False
            and overlay._settings["capture_system"] is False
        ), "both disabled when user wants silence"

    def test_apply_settings_resyncs_icons(self, overlay):
        overlay._settings["capture_mic"] = False
        overlay._settings["capture_system"] = False
        overlay.apply_settings(dict(overlay._settings))
        assert not overlay._mic_toggle.is_on()
        assert not overlay._sys_toggle.is_on()
