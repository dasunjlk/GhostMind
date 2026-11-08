"""Tests for the guided tutorial (C14): spotlight, navigation, skip rules.

All Qt-offscreen; no network. The tour must never trigger a real scan or
API call, so click-gating is verified with recorders.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import main as app_main
import ui.overlay_window as overlay_window
from tests.test_window_geometry import BASE_SETTINGS
from ui.overlay_window import OverlayWindow

STEP_COUNT = 18


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def overlay(qapp, monkeypatch):
    monkeypatch.setattr(
        overlay_window, "apply_stealth", lambda hwnd, click_through=False, dwm_cloak=False: None
    )
    win = OverlayWindow(dict(BASE_SETTINGS), Path("."))
    win.show()
    yield win
    if win._tutorial is not None:
        win._tutorial._finish(False)
    win.close()


def _esc(overlay: OverlayWindow) -> None:
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(ev)


def _advance(controller, times: int, qapp) -> None:
    for _ in range(times):
        controller._next()
        qapp.processEvents()


class TestFirstRun:
    def test_auto_starts_when_not_done(self, overlay):
        assert not overlay._settings.get("tutorial_done", False)
        overlay.maybe_start_first_run_tutorial()
        assert overlay._tutorial is not None
        assert overlay._tutorial.active
        assert len(overlay._tutorial._shades) == 4, "four-shade spotlight"
        assert overlay._tutorial._ring is not None

    def test_no_start_when_already_done(self, overlay):
        overlay._settings["tutorial_done"] = True
        overlay.maybe_start_first_run_tutorial()
        assert overlay._tutorial is None

    def test_first_banner_button_rules(self, overlay):
        overlay.maybe_start_first_run_tutorial()
        banner = overlay._tutorial._banner
        assert banner._skip_btn.isHidden(), "first run cannot be skipped"
        assert banner._back_btn.isHidden()
        assert not banner._next_btn.isHidden()
        assert banner._done_btn.isHidden()
        assert banner._counter.text() == f"Step 1 of {STEP_COUNT}"

    def test_first_run_esc_is_inert(self, overlay):
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        _esc(overlay)
        assert controller.active, "first-run tour cannot be skipped with Esc"
        assert overlay._tutorial is controller
        assert controller.index == 0

    def test_not_completed_tour_restarts_later(self, overlay):
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        controller._finish(False)  # abandoned mid-way
        assert overlay._tutorial is None
        overlay.maybe_start_first_run_tutorial()
        assert overlay._tutorial is not None, "incomplete first run is still a first run"


class TestNavigation:
    def test_next_opens_settings_on_general(self, overlay, qapp):
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        controller._next()
        qapp.processEvents()

        assert controller.index == 1
        assert overlay.is_settings_open()
        assert overlay._settings_panel._tabs.currentWidget() is overlay._settings_panel._general_tab

    def test_spotlight_matches_target(self, overlay, qapp):
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        controller._next()
        qapp.processEvents()

        monitor = overlay._settings_panel._monitor
        top_left = monitor.mapTo(overlay, monitor.rect().topLeft())
        ring = controller._ring
        assert ring.geometry().contains(top_left)
        assert overlay._settings_panel._monitor.geometry().width() <= ring.geometry().width()

    def test_shades_swallow_clicks(self, overlay, qapp):
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        shade = controller._shades[0]
        QTest.mouseClick(shade, Qt.MouseButton.LeftButton)
        assert controller.active, "shade click must not end or change the tour"
        assert controller.index == 0

    def test_back_returns(self, overlay, qapp):
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        _advance(controller, 3, qapp)
        assert controller.index == 3
        controller._back()
        assert controller.index == 2

    def test_last_step_is_done_only(self, overlay, qapp):
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        _advance(controller, STEP_COUNT - 1, qapp)

        assert controller.index == STEP_COUNT - 1
        assert controller._banner._next_btn.isHidden(), "last banner: no Next"
        assert not controller._banner._back_btn.isHidden()
        assert not controller._banner._done_btn.isHidden()
        assert len(controller._shades) == 0, "final step has no spotlight target"

    def test_done_emits_finished_completed(self, overlay, qapp):
        results: list[bool] = []
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        overlay.tutorial_finished.connect(results.append)
        _advance(controller, STEP_COUNT - 1, qapp)
        controller._banner._done_btn.click()

        assert results == [True]
        assert overlay._tutorial is None


class TestClickModes:
    def test_gear_passthrough_opens_settings_and_advances(self, overlay, qapp):
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        QTest.mouseClick(overlay._btn_set, Qt.MouseButton.LeftButton)
        qapp.processEvents()

        assert controller.index == 1, "clicking the highlighted gear advances"
        assert overlay.is_settings_open(), "the real gear action ran"

    def test_scan_block_does_not_trigger_a_scan(self, overlay, qapp, monkeypatch):
        scans: list[bool] = []
        monkeypatch.setattr(overlay, "trigger_screen_scan", lambda: scans.append(True))
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        _advance(controller, 14, qapp)  # step 15: the Scan button (home)

        assert controller._steps[controller.index].click_mode == "block"
        QTest.mouseClick(overlay._btn_scan, Qt.MouseButton.LeftButton)
        qapp.processEvents()

        assert scans == [], "tour must never trigger a real scan"
        assert controller.index == 15, "blocked click still advances"

    def test_check_button_blocked_does_not_call_api(self, overlay, qapp, monkeypatch):
        panel = overlay._settings_panel
        calls: list[bool] = []
        monkeypatch.setattr(panel, "_on_check_models", lambda *a, **k: calls.append(True))
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        _advance(controller, 10, qapp)  # step 11: Check Available Model

        assert controller._steps[controller.index].click_mode == "block"
        QTest.mouseClick(panel._check_btn, Qt.MouseButton.LeftButton)
        qapp.processEvents()

        assert calls == [], "tour must never trigger an API check"
        assert controller.index == 11


class TestReplay:
    def test_replay_shows_skip(self, overlay):
        overlay.start_tutorial(replay=True)
        assert overlay._tutorial is not None
        assert not overlay._tutorial._banner._skip_btn.isHidden()

    def test_replay_esc_skips(self, overlay):
        finished: list[bool] = []
        overlay.tutorial_finished.connect(finished.append)
        overlay.start_tutorial(replay=True)
        _esc(overlay)
        assert finished == [False]
        assert overlay._tutorial is None

    def test_replay_skip_button_finishes(self, overlay):
        finished: list[bool] = []
        overlay.tutorial_finished.connect(finished.append)
        overlay.start_tutorial(replay=True)
        overlay._tutorial._banner._skip_btn.click()
        assert finished == [False]

    def test_second_tour_while_active_is_ignored(self, overlay):
        overlay.start_tutorial(replay=True)
        first = overlay._tutorial
        overlay.start_tutorial(replay=True)
        assert overlay._tutorial is first


class TestReposition:
    def test_resize_remaps_spotlight(self, overlay, qapp):
        overlay.maybe_start_first_run_tutorial()
        controller = overlay._tutorial
        controller._next()  # General → monitor combo
        qapp.processEvents()

        overlay.resize(560, 640)
        qapp.processEvents()
        monitor = overlay._settings_panel._monitor
        top_left = monitor.mapTo(overlay, monitor.rect().topLeft())
        assert controller._ring.geometry().contains(top_left)


class TestMainPersistence:
    @pytest.fixture
    def controller(self, qapp, monkeypatch):
        monkeypatch.setattr(app_main, "resolve_api_key", lambda **kwargs: "")
        monkeypatch.setattr(
            app_main.GhostMindController, "_register_hotkeys", lambda self: None
        )
        ctrl = app_main.GhostMindController(qapp, dict(app_main.DEFAULT_SETTINGS))
        ctrl._update_timer.stop()
        yield ctrl
        ctrl._update_timer.stop()
        ctrl.hotkeys.unregister_all()
        ctrl.overlay.close_event_allowed = True
        ctrl.overlay.close()
        ctrl._tray.hide()
        ctrl.deleteLater()
        qapp.processEvents()

    def test_completed_persists_tutorial_done(self, controller, monkeypatch):
        saved: list[dict] = []
        monkeypatch.setattr(app_main, "save_settings", lambda s: saved.append(dict(s)))
        controller._on_tutorial_finished(True)

        assert controller.settings["tutorial_done"] is True
        assert saved, "completion must be written to disk"

    def test_skipped_does_not_persist(self, controller, monkeypatch):
        saved: list[dict] = []
        monkeypatch.setattr(app_main, "save_settings", lambda s: saved.append(dict(s)))
        controller.settings.pop("tutorial_done", None)
        controller._on_tutorial_finished(False)

        assert "tutorial_done" not in controller.settings
        assert saved == []
