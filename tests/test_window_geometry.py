"""Tests for R-04: window geometry persistence in OverlayWindow."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

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


class TestRestoreGeometry:
    def test_default_size_when_nothing_saved(self, overlay):
        assert overlay.width() == 480
        assert overlay.height() == 600

    def test_restores_saved_size(self, qapp):
        s = dict(BASE_SETTINGS, window_w=700, window_h=520)
        win = OverlayWindow(s, Path("."))
        try:
            assert (win.width(), win.height()) == (700, 520)
        finally:
            win.close()

    def test_restores_saved_position(self, qapp):
        s = dict(BASE_SETTINGS, window_x=60, window_y=70)
        win = OverlayWindow(s, Path("."))
        try:
            assert (win.x(), win.y()) == (60, 70)
        finally:
            win.close()

    def test_offscreen_position_is_clamped(self, qapp):
        s = dict(BASE_SETTINGS, window_x=50000, window_y=50000)
        win = OverlayWindow(s, Path("."))
        try:
            primary = QApplication.primaryScreen().availableGeometry()
            assert primary.contains(win.pos()) or primary.intersects(win.geometry())
        finally:
            win.close()

    def test_non_int_saved_values_fall_back_to_defaults(self, qapp):
        # toml may round-trip None as ""; treat as "not saved"
        s = dict(BASE_SETTINGS, window_x="", window_y="", window_w="", window_h="")
        win = OverlayWindow(s, Path("."))
        try:
            assert (win.width(), win.height()) == (480, 600)
        finally:
            win.close()


class TestGeometrySignals:
    def test_geometry_changed_emitted_on_move(self, overlay):
        captured = []
        overlay.geometry_changed.connect(captured.append)
        overlay.show()  # Qt only fires moveEvent on visible windows
        overlay.move(120, 90)
        QTest.qWait(700)  # debounce is 500ms
        assert captured, "geometry_changed was not emitted after move"
        geom = captured[-1]
        assert geom["window_x"] == 120
        assert geom["window_y"] == 90
        assert geom["window_w"] == 480
        assert geom["window_h"] == 600
        assert isinstance(geom["window_screen"], str)

    def test_no_geometry_changed_during_restore(self, qapp):
        captured = []
        s = dict(BASE_SETTINGS, window_x=80, window_y=90, window_w=640, window_h=480)
        win = OverlayWindow(s, Path("."))
        win.geometry_changed.connect(captured.append)
        try:
            # While hidden, restore must never persist anything. (Showing the
            # window later fires one benign moveEvent that re-saves identical
            # values — that is the mapped-position event, not the restore.)
            QTest.qWait(700)
            assert captured == [], "restore must not emit geometry_changed"
        finally:
            win.close()
