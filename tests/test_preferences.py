"""Tests for the Preferences tab (font size) and app-wide font application."""
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


class TestPreferencesTab:
    def test_tab_exists_with_spinbox(self, qapp):
        panel = SettingsPanel(dict(BASE_SETTINGS))
        names = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        assert "Preferences" in names
        assert panel._font_size.value() == 13

    def test_font_size_round_trip(self, qapp):
        panel = SettingsPanel(dict(BASE_SETTINGS))
        panel._font_size.setValue(18)
        out = panel.collect_data()
        assert out["font_size"] == 18

    def test_saved_value_loaded(self, qapp):
        data = dict(BASE_SETTINGS)
        data["font_size"] = 20
        panel = SettingsPanel(data)
        assert panel._font_size.value() == 20


class TestFontApplication:
    def test_overlay_font_applied(self, overlay):
        overlay.apply_font_size(17)
        assert overlay.font().pointSize() == 17

    def test_answer_blocks_get_font_size(self, overlay):
        overlay.apply_font_size(16)
        overlay._answer_panel.begin_answer_stream()
        overlay._answer_panel.append_stream_chunk("some answer text")
        overlay._answer_panel.end_stream_success()
        style = overlay._answer_panel._blocks[-1]._text.styleSheet()
        assert "16px" in style and "font-size" in style

    def test_new_blocks_inherit_current_size(self, overlay):
        overlay.apply_font_size(20)
        overlay._answer_panel.begin_answer_stream()
        style = overlay._answer_panel._blocks[-1]._text.styleSheet()
        assert "20px" in style and "font-size" in style

    def test_subtitle_bar_font(self, overlay):
        overlay.apply_font_size(19)
        style = overlay._subtitle_bar._view.styleSheet()
        assert "19px" in style and "font-size" in style

    def test_ask_input_font(self, overlay):
        overlay.apply_font_size(15)
        assert "font-size:15px" in overlay._ask_input.styleSheet()

    def test_clamped_to_valid_range(self, overlay):
        overlay.apply_font_size(999)
        assert overlay.font().pointSize() == 24
        overlay.apply_font_size(1)
        assert overlay.font().pointSize() == 9

    def test_settings_change_applies_font(self, overlay):
        data = dict(BASE_SETTINGS)
        data["font_size"] = 21
        overlay.apply_settings(data)
        assert overlay.font().pointSize() == 21
