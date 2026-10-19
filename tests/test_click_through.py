"""Tests for the click-through guard in OverlayWindow.

With click-through enabled, clicks pass through the overlay body while the
header bar and the open settings panel stay interactive (gear button, min /
close buttons, toggles) so the user can always turn click-through back off.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

import ui.overlay_window as overlay_window
from ui.overlay_window import OverlayWindow

BASE_SETTINGS = {
    "monitor_id": 1,
    "scan_mode": "manual",
    "auto_scan_interval_sec": 30,
    "opacity": 0.92,
    "click_through": False,
    "dwm_cloak": False,
    "subtitles_enabled": False,
    "capture_mic": False,
    "capture_system": False,
    "session_type": "meeting",
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


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def overlay(qapp):
    win = OverlayWindow(dict(BASE_SETTINGS), Path("."))
    yield win
    win.close()


@pytest.fixture
def stealth_spy(monkeypatch):
    """Capture the click_through value passed to apply_stealth."""
    calls = []

    def fake_apply(hwnd, click_through=False, dwm_cloak=False):
        calls.append(click_through)

    monkeypatch.setattr(overlay_window, "apply_stealth", fake_apply)
    return calls


def _header_point(overlay: OverlayWindow) -> QPoint:
    h = overlay._header
    return h.mapToGlobal(QPoint(h.width() // 2, h.height() // 2))


def _body_point(overlay: OverlayWindow) -> QPoint:
    h = overlay._header
    return h.mapToGlobal(QPoint(h.width() // 2, h.height() + 60))


class TestGuardTimer:
    def test_idle_when_click_through_off(self, overlay, stealth_spy):
        overlay.show()
        overlay.apply_settings({"click_through": False})
        assert not overlay._click_guard_timer.isActive()

    def test_runs_while_click_through_on(self, overlay, stealth_spy):
        overlay.show()
        overlay.apply_settings({"click_through": True})
        assert overlay._click_guard_timer.isActive()

    def test_stops_when_disabled_again(self, overlay, stealth_spy):
        overlay.show()
        overlay.apply_settings({"click_through": True})
        overlay.apply_settings({"click_through": False})
        assert not overlay._click_guard_timer.isActive()
        assert overlay._click_guard_interactive is False

    def test_stops_when_window_hidden(self, overlay, stealth_spy):
        overlay.show()
        overlay.apply_settings({"click_through": True})
        overlay.hide()
        overlay._update_click_guard()
        assert not overlay._click_guard_timer.isActive()


class TestPointerZones:
    def test_pointer_in_header_geometry(self, overlay, monkeypatch):
        overlay.show()
        monkeypatch.setattr(
            overlay_window, "_global_cursor_pos", lambda: _header_point(overlay)
        )
        assert overlay._pointer_in_header() is True
        monkeypatch.setattr(
            overlay_window, "_global_cursor_pos", lambda: _body_point(overlay)
        )
        assert overlay._pointer_in_header() is False

    def test_header_hover_drops_click_through(self, overlay, stealth_spy, monkeypatch):
        overlay.show()
        overlay.apply_settings({"click_through": True})
        stealth_spy.clear()
        monkeypatch.setattr(
            overlay_window, "_global_cursor_pos", lambda: _header_point(overlay)
        )
        overlay._update_click_guard()
        assert overlay._click_guard_interactive is True
        assert stealth_spy == [False]

    def test_leaving_header_restores_click_through(self, overlay, stealth_spy, monkeypatch):
        overlay.show()
        overlay.apply_settings({"click_through": True})
        monkeypatch.setattr(
            overlay_window, "_global_cursor_pos", lambda: _header_point(overlay)
        )
        overlay._update_click_guard()
        stealth_spy.clear()
        monkeypatch.setattr(
            overlay_window, "_global_cursor_pos", lambda: _body_point(overlay)
        )
        overlay._update_click_guard()
        assert overlay._click_guard_interactive is False
        assert stealth_spy == [True]


class TestSettingsPanel:
    def test_open_settings_stays_interactive(self, overlay, stealth_spy, monkeypatch):
        overlay.show()
        overlay.apply_settings({"click_through": True})
        monkeypatch.setattr(
            overlay_window, "_global_cursor_pos", lambda: _body_point(overlay)
        )
        overlay._stack.setCurrentIndex(1)
        stealth_spy.clear()
        overlay._update_click_guard()
        assert overlay._click_guard_interactive is True
        assert stealth_spy == [False]

    def test_closing_settings_restores_click_through(self, overlay, stealth_spy, monkeypatch):
        overlay.show()
        overlay.apply_settings({"click_through": True})
        monkeypatch.setattr(
            overlay_window, "_global_cursor_pos", lambda: _body_point(overlay)
        )
        overlay._stack.setCurrentIndex(1)
        overlay._update_click_guard()
        overlay._stack.setCurrentIndex(0)
        stealth_spy.clear()
        overlay._update_click_guard()
        assert overlay._click_guard_interactive is False
        assert stealth_spy == [True]

    def test_saving_click_through_off_clears_everything(self, overlay, stealth_spy, monkeypatch):
        """Regression: after enabling click-through, saving it 'off' must
        restore a fully interactive window (previously it could not be undone)."""
        overlay.show()
        overlay.apply_settings({"click_through": True})
        monkeypatch.setattr(
            overlay_window, "_global_cursor_pos", lambda: _body_point(overlay)
        )
        overlay._stack.setCurrentIndex(1)
        overlay._update_click_guard()
        stealth_spy.clear()
        overlay.apply_settings({"click_through": False})
        assert overlay._click_guard_interactive is False
        assert not overlay._click_guard_timer.isActive()
        assert stealth_spy[-1] is False
