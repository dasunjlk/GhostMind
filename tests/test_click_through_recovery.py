"""Tests for click-through recovery through the tray, banner, and hotkey."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

import main as app_main


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def controller(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "resolve_api_key", lambda: "")
    monkeypatch.setattr(app_main, "save_settings", lambda settings: None)
    monkeypatch.setattr(
        app_main.GhostMindController, "_register_hotkeys", lambda self: None
    )
    ctrl = app_main.GhostMindController(qapp, dict(app_main.DEFAULT_SETTINGS))
    yield ctrl
    ctrl._update_timer.stop()
    ctrl.hotkeys.unregister_all()
    ctrl.overlay.close_event_allowed = True
    ctrl.overlay.close()
    ctrl._tray.hide()
    ctrl.deleteLater()
    qapp.processEvents()


class TestTrayClickThrough:
    def test_tray_has_click_through_toggle_off_by_default(self, controller):
        action = controller._click_through_action
        assert action.isCheckable()
        assert not action.isChecked()
        assert action.text() == "Click-through: off"
        assert action in controller._tray_actions

    def test_tray_toggle_on_shows_banner_and_updates_action(self, controller, qapp):
        overlay = controller.overlay
        overlay.show()
        qapp.processEvents()

        controller._click_through_action.trigger()
        qapp.processEvents()

        assert controller.settings["click_through"] is True
        assert overlay._settings["click_through"] is True
        assert controller._click_through_action.isChecked()
        assert controller._click_through_action.text() == "Click-through: on"
        assert overlay._ct_banner.isVisible()
        assert overlay._click_guard_timer.isActive()

    def test_tray_toggle_twice_restores_interaction(self, controller, qapp):
        overlay = controller.overlay
        overlay.show()
        qapp.processEvents()
        action = controller._click_through_action

        action.trigger()
        action.trigger()
        qapp.processEvents()

        assert controller.settings["click_through"] is False
        assert overlay._settings["click_through"] is False
        assert not action.isChecked()
        assert action.text() == "Click-through: off"
        assert overlay._ct_banner.isHidden()
        assert not overlay._click_guard_timer.isActive()


class TestRecoveryPaths:
    def test_hotkey_turns_click_through_off(self, controller):
        controller._set_click_through(True)
        assert controller.settings["click_through"] is True

        controller._toggle_click_through()

        assert controller.settings["click_through"] is False
        assert controller.overlay._settings["click_through"] is False
        assert not controller._click_through_action.isChecked()

    def test_banner_button_turns_click_through_off(self, controller, qapp):
        overlay = controller.overlay
        overlay.show()
        controller._set_click_through(True)
        qapp.processEvents()

        overlay._ct_banner._disable_btn.click()
        qapp.processEvents()

        assert controller.settings["click_through"] is False
        assert overlay._settings["click_through"] is False
        assert not controller._click_through_action.isChecked()
        assert controller._click_through_action.text() == "Click-through: off"
        assert overlay._ct_banner.isHidden()


class TestSettingsOpenSafety:
    def test_tray_settings_turns_click_through_off(self, controller, qapp):
        overlay = controller.overlay
        controller._set_click_through(True)
        assert controller.settings["click_through"] is True

        controller._tray_open_settings()
        qapp.processEvents()

        assert overlay._stack.currentIndex() == 1
        assert controller.settings["click_through"] is False
        assert overlay._settings["click_through"] is False
        assert not controller._click_through_action.isChecked()
        assert controller._click_through_action.text() == "Click-through: off"
        assert overlay._ct_banner.isHidden()

    def test_tray_toggle_cannot_enable_while_settings_open(self, controller, qapp):
        overlay = controller.overlay
        overlay.open_settings()
        qapp.processEvents()

        controller._click_through_action.trigger()
        qapp.processEvents()

        assert controller.settings["click_through"] is False
        assert overlay._settings["click_through"] is False
        assert not controller._click_through_action.isChecked()
        assert controller._click_through_action.text() == "Click-through: off"

    def test_hotkey_cannot_enable_while_settings_open(self, controller):
        controller.overlay.open_settings()

        controller._toggle_click_through()

        assert controller.settings["click_through"] is False
        assert controller.overlay._settings["click_through"] is False
        assert not controller._click_through_action.isChecked()
