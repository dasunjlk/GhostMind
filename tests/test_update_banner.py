"""Tests for the in-app update banner (C6).

Covers the widget, the overlay integration (settings interplay, click-through
guard zone), and the controller flow: a grace-phase update check shows the
banner instead of the popup, a locked check still forces the popup, and
'Later' snoozes via the updater state recorder.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

import main as app_main
import ui.overlay_window as overlay_window
import utils.updater as updater
from tests.test_window_geometry import BASE_SETTINGS
from ui.overlay_window import OverlayWindow
from ui.update_banner import UpdateBanner
from utils.updater import UpdateCheck


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def overlay(qapp, monkeypatch):
    monkeypatch.setattr(
        overlay_window,
        "apply_stealth",
        lambda hwnd, click_through=False, dwm_cloak=False: None,
    )
    win = OverlayWindow(dict(BASE_SETTINGS), Path("."))
    yield win
    win.close()


@pytest.fixture
def controller(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "resolve_api_key", lambda **kwargs: "")
    monkeypatch.setattr(
        app_main.GhostMindController, "_register_hotkeys", lambda self: None
    )
    ctrl = app_main.GhostMindController(qapp, dict(app_main.DEFAULT_SETTINGS))
    ctrl._update_timer.stop()
    yield ctrl
    ctrl._update_timer.stop()
    if ctrl._update_popup is not None:
        ctrl._update_popup.close()
        ctrl._update_popup.deleteLater()
    ctrl.hotkeys.unregister_all()
    ctrl.overlay.close_event_allowed = True
    ctrl.overlay.close()
    ctrl._tray.hide()
    ctrl.deleteLater()
    qapp.processEvents()


def _grace_check(**overrides) -> UpdateCheck:
    fields = dict(
        tag="1.1.0",
        notes="Test notes",
        assets=[],
        update_available=True,
        locked=False,
        should_popup=True,
        now=1_000_000,
        state={},
    )
    fields.update(overrides)
    return UpdateCheck(**fields)


class TestUpdateBannerWidget:
    def test_hidden_by_default(self, qapp):
        banner = UpdateBanner()
        assert banner.isHidden()

    def test_set_version_updates_label(self, qapp):
        banner = UpdateBanner()
        banner.set_version("1.2.0")
        assert "1.2.0" in banner._label.text()
        assert "available" in banner._label.text()

    def test_set_version_empty_falls_back_to_generic_text(self, qapp):
        banner = UpdateBanner()
        banner.set_version("")
        assert banner._label.text() == "Update available"

    def test_actions_emit_signals(self, qapp):
        banner = UpdateBanner()
        seen: List[str] = []
        banner.whats_new_requested.connect(lambda: seen.append("whats_new"))
        banner.update_requested.connect(lambda: seen.append("update"))
        banner.later_requested.connect(lambda: seen.append("later"))
        banner._whats_new_btn.click()
        banner._update_btn.click()
        banner._later_btn.click()
        assert seen == ["whats_new", "update", "later"]


class TestOverlayIntegration:
    def test_show_and_hide_banner(self, overlay, qapp):
        overlay.show()
        overlay.show_update_banner("1.1.0")
        assert overlay._update_banner.isVisible()
        assert "1.1.0" in overlay._update_banner._label.text()
        assert overlay._update_banner_active
        overlay.hide_update_banner()
        assert not overlay._update_banner.isVisible()
        assert not overlay._update_banner_active

    def test_banner_hidden_while_settings_open_then_restored(self, overlay, qapp):
        overlay.show()
        overlay.show_update_banner("1.1.0")
        assert overlay._update_banner.isVisible()
        overlay.open_settings()
        assert not overlay._update_banner.isVisible()
        assert overlay._update_banner_active, "banner must survive the settings visit"
        overlay._close_settings()
        assert overlay._update_banner.isVisible()

    def test_show_while_settings_open_waits_for_close(self, overlay, qapp):
        overlay.show()
        overlay.open_settings()
        overlay.show_update_banner("1.1.0")
        assert overlay._update_banner_active
        assert not overlay._update_banner.isVisible()
        overlay._close_settings()
        assert overlay._update_banner.isVisible()

    def test_banner_is_a_click_through_guard_zone(self, overlay, qapp, monkeypatch):
        overlay.show()
        overlay.apply_settings({"click_through": True})
        overlay.show_update_banner("1.1.0")
        banner = overlay._update_banner
        over = banner.mapToGlobal(QPoint(banner.width() // 2, banner.height() // 2))
        monkeypatch.setattr(overlay_window, "_global_cursor_pos", lambda: over)
        overlay._update_click_guard()
        assert overlay._click_guard_interactive is True

        away = QPoint(999_999, 999_999)
        monkeypatch.setattr(overlay_window, "_global_cursor_pos", lambda: away)
        overlay._update_click_guard()
        assert overlay._click_guard_interactive is False


class TestControllerBannerFlow:
    def test_grace_check_shows_banner_not_popup(self, controller):
        controller.overlay.show()
        controller._on_update_check_done(_grace_check())
        assert controller.overlay._update_banner.isVisible()
        assert controller._update_popup is None, "grace phase must not popup (C6)"

    def test_banner_shows_remote_version(self, controller):
        controller.overlay.show()
        controller._on_update_check_done(_grace_check(tag="1.2.3"))
        assert "1.2.3" in controller.overlay._update_banner._label.text()

    def test_snoozed_check_keeps_banner_hidden(self, controller):
        controller.overlay.show()
        check = _grace_check(state={"snooze_until_epoch": 2_000_000}, now=1_000_000)
        controller._on_update_check_done(check)
        assert not controller.overlay._update_banner.isVisible()
        assert not controller.overlay._update_banner_active

    def test_later_records_snooze_and_hides_banner(self, controller, monkeypatch):
        calls: List[int] = []
        monkeypatch.setattr(
            updater, "record_snooze", lambda *a, **kw: calls.append(True)
        )
        controller.overlay.show()
        controller._on_update_check_done(_grace_check())
        assert controller.overlay._update_banner.isVisible()
        controller.overlay._update_banner._later_btn.click()
        assert calls == [True]
        assert not controller.overlay._update_banner.isVisible()
        assert not controller.overlay._update_banner_active

    def test_locked_check_forces_popup_and_hides_banner(self, controller):
        controller.overlay.show()
        check = _grace_check(locked=True, days_left=0)
        controller._on_update_check_done(check)
        assert controller._update_popup is not None
        assert controller._update_popup.isVisible()
        assert not controller.overlay._update_banner.isVisible()

    def test_banner_details_open_the_popup(self, controller):
        controller.overlay.show()
        controller._on_update_check_done(_grace_check())
        controller.overlay._update_banner._whats_new_btn.click()
        assert controller._update_popup is not None
        assert controller._update_popup.isVisible()

    def test_banner_update_button_opens_the_popup(self, controller):
        controller.overlay.show()
        controller._on_update_check_done(_grace_check())
        controller.overlay._update_banner._update_btn.click()
        assert controller._update_popup is not None
        assert controller._update_popup.isVisible()

    def test_locked_update_lock_hides_banner(self, controller):
        controller.overlay.show()
        controller._on_update_check_done(_grace_check())
        assert controller.overlay._update_banner.isVisible()
        controller._enter_update_lock(_grace_check(locked=True, days_left=0))
        assert not controller.overlay._update_banner.isVisible()
