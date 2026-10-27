"""Tests for reaching Settings from the tray and the first-run API-key CTA."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QPushButton

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


def _find_action(controller, text: str):
    for action in controller._tray_menu.actions():
        if action.text() == text:
            return action
    return None


def _close_button(controller) -> QPushButton:
    for button in controller.overlay._settings_panel.findChildren(QPushButton):
        if button.text() == "Close":
            return button
    raise AssertionError("Settings Close button not found")


class TestTraySettings:
    def test_tray_menu_has_settings_action(self, controller):
        action = _find_action(controller, "Settings…")
        assert action is not None
        assert action.isVisible()

    def test_tray_settings_shows_overlay_and_opens_settings(self, controller, qapp):
        overlay = controller.overlay
        overlay._visible_target = False
        overlay.hide()
        assert not overlay.isVisible()

        action = _find_action(controller, "Settings…")
        assert action is not None
        action.trigger()
        qapp.processEvents()

        assert overlay.isVisible()
        assert overlay._stack.currentIndex() == 1
        assert not overlay._settings_panel.isHidden()


class TestKeySetupCta:
    def test_cta_visible_when_no_key_is_available(self, controller):
        cta = controller.overlay._answer_panel._key_cta
        assert not cta.isHidden()

    def test_cta_hidden_when_key_is_available(self, controller, monkeypatch):
        cta = controller.overlay._answer_panel._key_cta
        monkeypatch.setattr(app_main, "resolve_api_key", lambda: "gsk_test")
        controller._refresh_api_key_cta()
        assert cta.isHidden()

    def test_cta_opens_api_tab(self, controller, qapp):
        overlay = controller.overlay
        overlay._answer_panel._key_cta_btn.click()
        qapp.processEvents()

        panel = overlay._settings_panel
        assert overlay._stack.currentIndex() == 1
        assert panel._tabs.currentWidget() is panel._api_tab


class TestSettingsNavigation:
    def test_close_button_returns_to_answers(self, controller, qapp):
        overlay = controller.overlay
        overlay.open_settings()
        assert overlay._stack.currentIndex() == 1

        _close_button(controller).click()
        qapp.processEvents()

        assert overlay._stack.currentIndex() == 0
        assert overlay._settings_panel.isHidden()

    def test_closing_settings_refreshes_cta(self, controller, monkeypatch):
        cta = controller.overlay._answer_panel._key_cta
        assert not cta.isHidden()

        monkeypatch.setattr(app_main, "resolve_api_key", lambda: "gsk_test")
        controller.overlay.open_settings()
        controller.overlay._close_settings()

        assert cta.isHidden()
