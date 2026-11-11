"""Tests for the Settings API-key save flow (per-host keys)."""
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
    monkeypatch.setattr(key_store, "load_key_for", lambda host: "")
    monkeypatch.setattr(key_store, "is_keyring_available", lambda: True)
    widget = SettingsPanel(dict(BASE_SETTINGS))
    yield widget
    widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def overlay(qapp, monkeypatch):
    monkeypatch.setattr(key_store, "load_key_for", lambda host: "")
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


def _patch_validation(monkeypatch, result=(True, "API key works - 'qwen/qwen3.8-27b' is ready.")):
    calls: list = []

    def _validate(api_key=None, model_id=None, base_url=None):
        calls.append((api_key, model_id, base_url))
        return result

    monkeypatch.setattr(ai_engine, "validate_key_and_model", _validate)
    monkeypatch.setattr(settings_panel_module.threading, "Thread", _ImmediateThread)
    return calls


class TestSuccessfulKeySave:
    def test_success_reports_emits_and_clears_field(self, panel, monkeypatch):
        saved: list = []
        save_calls: list = []
        validation_calls = _patch_validation(monkeypatch)
        monkeypatch.setattr(
            key_store,
            "save_key_for",
            lambda host, key: save_calls.append((host, key)) or "keyring",
        )
        panel.saved.connect(saved.append)
        panel._api_key.setText("  gsk_test_key  ")

        panel._emit_save()

        assert save_calls == [("api.groq.com", "gsk_test_key")]
        assert validation_calls == [
            ("gsk_test_key", BASE_SETTINGS["ai_model"], BASE_SETTINGS["api_base_url"])
        ]
        assert len(saved) == 1
        assert panel._api_key.text() == ""
        assert "Key saved" in panel._key_status.text()
        assert "Windows Credential Manager" in panel._key_status.text()
        assert "#00FF88" in panel._key_status.styleSheet()

    def test_plaintext_fallback_counts_as_saved(self, panel, monkeypatch):
        saved: list = []
        _patch_validation(monkeypatch)
        monkeypatch.setattr(key_store, "save_key_for", lambda host, key: "plaintext")
        panel.saved.connect(saved.append)
        panel._api_key.setText("gsk_plain")

        panel._emit_save()

        assert len(saved) == 1
        assert "plaintext fallback" in panel._key_status.text()

    def test_blank_field_keeps_stored_key(self, panel, monkeypatch):
        saved: list = []
        save_calls: list = []
        _patch_validation(monkeypatch)
        monkeypatch.setattr(key_store, "load_key_for", lambda host: "gsk_stored")
        monkeypatch.setattr(
            key_store,
            "save_key_for",
            lambda host, key: save_calls.append((host, key)) or "keyring",
        )
        panel.saved.connect(saved.append)

        panel._emit_save()

        assert save_calls == []
        assert len(saved) == 1
        assert "Key stored for api.groq.com" in panel._key_status.text()

    def test_successful_check_skips_validation_on_save(self, panel, monkeypatch):
        saved: list = []
        save_calls: list = []

        def _discover(api_key=None, base_url=None, model_id=None):
            return (
                True,
                "Connected to api.groq.com — 2 models available.",
                [BASE_SETTINGS["ai_model"], "openai/gpt-oss-20b"],
            )

        monkeypatch.setattr(ai_engine, "discover_models", _discover)
        monkeypatch.setattr(settings_panel_module.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(
            key_store,
            "save_key_for",
            lambda host, key: save_calls.append((host, key)) or "keyring",
        )

        def _unexpected_validate(**kwargs):
            raise AssertionError("Save must reuse a successful Check")

        monkeypatch.setattr(ai_engine, "validate_key_and_model", _unexpected_validate)
        panel.saved.connect(saved.append)
        panel._api_key.setText("gsk_checked")

        panel._on_check_models()
        panel._emit_save()

        assert save_calls == [("api.groq.com", "gsk_checked")]
        assert len(saved) == 1


class TestFailedKeySave:
    def test_failure_stays_inline_and_does_not_emit_saved(self, panel, monkeypatch):
        saved: list = []
        _patch_validation(monkeypatch)

        def _fail(host, key):
            raise RuntimeError("credential vault locked")

        monkeypatch.setattr(key_store, "save_key_for", _fail)
        panel.saved.connect(saved.append)
        panel._api_key.setText("gsk_secret")

        panel._emit_save()

        assert saved == []
        assert panel._api_key.text() == "gsk_secret"
        assert "Could not save key" in panel._key_status.text()
        assert "credential vault locked" in panel._key_status.text()
        assert "#FF5555" in panel._key_status.styleSheet()
        assert panel._tabs.currentWidget() is panel._api_tab

    def test_failure_keeps_settings_page_open(self, overlay, monkeypatch):
        panel = overlay._settings_panel
        overlay.open_settings()
        panel._api_key.setText("gsk_secret")
        _patch_validation(monkeypatch)

        def _fail(host, key):
            raise RuntimeError("save failed")

        monkeypatch.setattr(key_store, "save_key_for", _fail)

        _save_button(panel).click()

        assert overlay.is_settings_open() is True
        assert panel._api_key.text() == "gsk_secret"
        assert "Could not save key" in panel._key_status.text()

    def test_validation_failure_blocks_save(self, panel, monkeypatch):
        saved: list = []
        save_calls: list = []
        _patch_validation(
            monkeypatch,
            result=(
                False,
                "Your API key was rejected by api.groq.com — paste it again "
                "from the provider's dashboard.",
            ),
        )
        monkeypatch.setattr(
            key_store,
            "save_key_for",
            lambda host, key: save_calls.append((host, key)) or "keyring",
        )
        panel.saved.connect(saved.append)
        panel._api_key.setText("gsk_bad")

        panel._emit_save()

        assert saved == []
        assert save_calls == []
        assert panel._api_key.text() == "gsk_bad"
        assert "rejected" in panel._key_status.text().lower()
        assert "#FF5555" in panel._key_status.styleSheet()
        assert panel._tabs.currentWidget() is panel._api_tab

    def test_model_required_blocks_save(self, panel, monkeypatch):
        saved: list = []
        validation_calls = _patch_validation(monkeypatch)

        def _unexpected_save(host, key):
            raise AssertionError("must not save without a model")

        monkeypatch.setattr(key_store, "save_key_for", _unexpected_save)
        panel.saved.connect(saved.append)
        panel._ai_model.clearEditText()

        panel._emit_save()

        assert saved == []
        assert validation_calls == []
        assert "model" in panel._key_status.text().lower()
        assert "#FF5555" in panel._key_status.styleSheet()
