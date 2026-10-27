"""Tests for the Settings API-key save flow."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QPushButton

import core.ai_engine as ai_engine
import ui.settings_panel as settings_panel_module
from tests.test_window_geometry import BASE_SETTINGS
from ui.overlay_window import OverlayWindow
from ui.settings_panel import SettingsPanel
from utils import key_store


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def panel(qapp, monkeypatch):
    monkeypatch.setattr(key_store, "load_key", lambda: "")
    monkeypatch.setattr(key_store, "is_keyring_available", lambda: True)
    widget = SettingsPanel(dict(BASE_SETTINGS))
    yield widget
    widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def overlay(qapp, monkeypatch):
    monkeypatch.setattr(key_store, "load_key", lambda: "")
    monkeypatch.setattr(key_store, "is_keyring_available", lambda: True)
    win = OverlayWindow(dict(BASE_SETTINGS), Path("."))
    yield win
    win.close_event_allowed = True
    win.close()


def _save_button(panel: SettingsPanel) -> QPushButton:
    for button in panel.findChildren(QPushButton):
        if button.text() == "Save":
            return button
    raise AssertionError("Save button not found")


class _ImmediateThread:
    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


class TestSuccessfulKeySave:
    def test_success_reports_emits_and_clears_field(self, panel, monkeypatch):
        saved: list = []
        save_calls: list = []
        test_calls: list = []
        monkeypatch.setattr(
            key_store,
            "save_key",
            lambda key: save_calls.append(key) or "keyring",
        )
        monkeypatch.setattr(
            panel, "_on_test_api", lambda key="": test_calls.append(key)
        )
        panel.saved.connect(saved.append)
        panel._api_key.setText("  gsk_test_key  ")

        panel._emit_save()

        assert save_calls == ["gsk_test_key"]
        assert len(saved) == 1
        assert test_calls == ["gsk_test_key"]
        assert panel._api_key.text() == ""
        assert "Key saved" in panel._key_status.text()
        assert "Windows Credential Manager" in panel._key_status.text()
        assert "#00FF88" in panel._key_status.styleSheet()

    def test_plaintext_fallback_counts_as_saved(self, panel, monkeypatch):
        saved: list = []
        test_calls: list = []
        monkeypatch.setattr(key_store, "save_key", lambda key: "plaintext")
        monkeypatch.setattr(
            panel, "_on_test_api", lambda key="": test_calls.append(key)
        )
        panel.saved.connect(saved.append)
        panel._api_key.setText("gsk_plain")

        panel._emit_save()

        assert len(saved) == 1
        assert test_calls == ["gsk_plain"]
        assert "plaintext fallback" in panel._key_status.text()

    def test_blank_field_keeps_stored_key(self, panel, monkeypatch):
        saved: list = []
        save_calls: list = []
        test_calls: list = []
        monkeypatch.setattr(
            key_store,
            "save_key",
            lambda key: save_calls.append(key) or "keyring",
        )
        monkeypatch.setattr(
            panel, "_on_test_api", lambda key="": test_calls.append(key)
        )
        panel.saved.connect(saved.append)

        panel._emit_save()

        assert save_calls == []
        assert len(saved) == 1
        assert test_calls == [""]


class TestFailedKeySave:
    def test_failure_stays_inline_and_does_not_emit_saved(self, panel, monkeypatch):
        saved: list = []
        test_calls: list = []
        warnings: list = []

        def _fail(key):
            raise RuntimeError("credential vault locked")

        monkeypatch.setattr(key_store, "save_key", _fail)
        monkeypatch.setattr(
            panel, "_on_test_api", lambda key="": test_calls.append(key)
        )
        monkeypatch.setattr(
            settings_panel_module.QMessageBox,
            "warning",
            lambda *args, **kwargs: warnings.append(args),
        )
        panel.saved.connect(saved.append)
        panel._api_key.setText("gsk_secret")

        panel._emit_save()

        assert saved == []
        assert test_calls == []
        assert warnings == []
        assert panel._api_key.text() == "gsk_secret"
        assert "Could not save key" in panel._key_status.text()
        assert "credential vault locked" in panel._key_status.text()
        assert "#FF5555" in panel._key_status.styleSheet()
        assert panel._tabs.currentWidget() is panel._api_tab

    def test_failure_keeps_settings_page_open(self, overlay, monkeypatch):
        panel = overlay._settings_panel
        overlay.open_settings()
        panel._api_key.setText("gsk_secret")

        def _fail(key):
            raise RuntimeError("save failed")

        monkeypatch.setattr(key_store, "save_key", _fail)

        _save_button(panel).click()

        assert overlay.is_settings_open() is True
        assert panel._api_key.text() == "gsk_secret"
        assert "Could not save key" in panel._key_status.text()


class TestExplicitKeyValidation:
    def test_on_test_api_forwards_explicit_key(self, panel, monkeypatch):
        calls: list = []

        def _validate(api_key=None, model_id=None):
            calls.append((api_key, model_id))
            return True, "API key and model are ready."

        monkeypatch.setattr(ai_engine, "validate_key_and_model", _validate)
        monkeypatch.setattr(
            settings_panel_module.threading, "Thread", _ImmediateThread
        )

        panel._on_test_api("  gsk_explicit  ")

        assert calls == [("gsk_explicit", BASE_SETTINGS["ai_model"])]
        assert "ready" in panel._key_status.text().lower()
        assert panel._check_btn.isEnabled() is True

    def test_check_button_validates_typed_key(self, panel, monkeypatch):
        calls: list = []

        def _validate(api_key=None, model_id=None):
            calls.append((api_key, model_id))
            return True, "API key and model are ready."

        monkeypatch.setattr(ai_engine, "validate_key_and_model", _validate)
        monkeypatch.setattr(
            settings_panel_module.threading, "Thread", _ImmediateThread
        )
        panel._api_key.setText("  gsk_typed  ")

        panel._check_btn.click()

        assert calls == [("gsk_typed", BASE_SETTINGS["ai_model"])]

    def test_check_button_does_not_pass_clicked_bool(self, panel, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            panel, "_on_test_api", lambda key="": calls.append(key)
        )

        panel._check_btn.click()

        assert calls == [""]
