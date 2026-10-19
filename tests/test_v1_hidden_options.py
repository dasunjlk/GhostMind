"""Tests for the v1.0 hidden listening/subtitle surfaces.

Everything is hidden, not deleted: widgets and code paths stay intact so the
features can be re-enabled later (see future-plan.md hidden-features checklist).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from tests.test_window_geometry import BASE_SETTINGS
from ui.overlay_window import OverlayWindow
from ui.settings_panel import SettingsPanel


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


class TestOverlayV1Cuts:
    def test_header_toggles_hidden(self, overlay):
        assert overlay._mic_toggle.isHidden()
        assert overlay._sys_toggle.isHidden()

    def test_subtitles_tab_hidden(self, overlay):
        assert overlay._tabs.tabText(1) == "Subtitles"
        assert not overlay._tabs.isTabVisible(1)

    def test_toggle_subtitles_hotkey_is_inert(self, overlay):
        assert overlay._tabs.currentIndex() == 0
        overlay.toggle_subtitles_tab()
        assert overlay._tabs.currentIndex() == 0


class TestSettingsV1Cuts:
    def test_audio_tab_hidden(self, qapp):
        panel = SettingsPanel(dict(BASE_SETTINGS))
        names = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        assert names == ["General", "Audio", "Shortcuts", "API", "Preferences", "About"]
        assert not panel._tabs.isTabVisible(1)  # Audio

    def test_subtitle_and_export_rows_hidden(self, qapp):
        panel = SettingsPanel(dict(BASE_SETTINGS))
        assert panel._subtitles_startup.isHidden()
        assert panel._hk_sub.isHidden()
        assert panel._hk_export.isHidden()


class TestDefaultsV1Cuts:
    def test_listening_defaults_off(self):
        from main import DEFAULT_SETTINGS

        assert DEFAULT_SETTINGS["subtitles_enabled"] is False
        assert DEFAULT_SETTINGS["capture_mic"] is False
        assert DEFAULT_SETTINGS["capture_system"] is False

    def test_audio_listener_never_starts(self):
        from main import GhostMindController

        stub = type("Stub", (), {"settings": {}, "_audio": None})()
        GhostMindController._start_audio_if_needed(stub)
        assert stub._audio is None
