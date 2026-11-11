"""Tests for the provider settings UI and per-host model discovery (C2)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import toml
from PyQt6.QtWidgets import QApplication

import core.ai_engine as ai_engine
import main as app_main
import ui.settings_panel as settings_panel_module
from core.ai_engine import (
    DEFAULT_BASE_URL,
    discover_models,
    host_for_base_url,
    normalize_base_url,
    resolve_api_key,
)
from tests.test_window_geometry import BASE_SETTINGS
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


class _ImmediateThread:
    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


class _FakeKeyring:
    def __init__(self) -> None:
        self._store: dict = {}

    def get_password(self, service: str, name: str):
        return self._store.get((service, name))

    def set_password(self, service: str, name: str, secret: str) -> None:
        self._store[(service, name)] = secret

    def delete_password(self, service: str, name: str) -> None:
        self._store.pop((service, name), None)


@pytest.fixture
def fake_keys(monkeypatch, tmp_path):
    fake = _FakeKeyring()
    monkeypatch.setattr(key_store, "_KEYRING", fake, raising=False)
    monkeypatch.setattr(key_store, "_fallback_path", lambda: tmp_path / "settings.toml")
    return fake


def _combo_ids(panel: SettingsPanel) -> list:
    return [panel._ai_model.itemData(i) for i in range(panel._ai_model.count())]


class TestUrlValidation:
    def test_blank_defaults_to_groq(self):
        assert normalize_base_url("") == DEFAULT_BASE_URL
        assert normalize_base_url(None) == DEFAULT_BASE_URL

    def test_url_without_scheme_is_rejected(self):
        with pytest.raises(ValueError) as exc:
            normalize_base_url("api.groq.com/openai/v1")
        assert "base url" in str(exc.value).lower()

    def test_trailing_slash_is_removed(self):
        assert (
            normalize_base_url("https://openrouter.ai/api/v1/")
            == "https://openrouter.ai/api/v1"
        )

    def test_host_extraction(self):
        assert host_for_base_url(DEFAULT_BASE_URL) == "api.groq.com"
        assert host_for_base_url("https://openrouter.ai/api/v1") == "openrouter.ai"
        assert host_for_base_url("http://localhost:11434/v1") == "localhost:11434"
        assert host_for_base_url("not a url") == ""


class TestDefaultSettingsAndMigration:
    def test_default_base_url_setting(self):
        assert app_main.DEFAULT_SETTINGS["api_base_url"] == DEFAULT_BASE_URL

    def test_absent_base_url_migrates_to_groq(self, monkeypatch, tmp_path):
        config = tmp_path / "settings.toml"
        config.write_text('ai_model = "qwen/qwen3.8-27b"\n', encoding="utf-8")
        monkeypatch.setattr(app_main, "CONFIG_PATH", config)

        data = app_main.load_settings()

        assert data["api_base_url"] == DEFAULT_BASE_URL

    def test_save_settings_preserves_stored_keys(self, monkeypatch, tmp_path):
        config = tmp_path / "settings.toml"
        config.write_text(
            'ai_model = "qwen/qwen3.8-27b"\n'
            '[key_storage."api.groq.com"]\n'
            'api_key = "gsk_keep"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(app_main, "CONFIG_PATH", config)

        app_main.save_settings({"ai_model": "qwen/qwen3.8-27b", "opacity": 0.9})

        data = toml.load(config)
        assert data["key_storage"]["api.groq.com"]["api_key"] == "gsk_keep"
        assert data["opacity"] == 0.9


class TestPerHostKeyIntegration:
    def test_roundtrip_and_migration(self, fake_keys):
        assert key_store.save_key_for("openrouter.ai", "sk-or-test") == "keyring"
        assert key_store.load_key_for("openrouter.ai") == "sk-or-test"

        fake_keys._store[
            (key_store.SERVICE_NAME, key_store.LEGACY_KEY_NAME)
        ] = "gsk_legacy"
        assert key_store.load_key_for("api.groq.com") == "gsk_legacy"
        assert key_store.load_key_for("openrouter.ai") == "sk-or-test"

    def test_resolve_uses_key_for_current_host(self, monkeypatch):
        seen: list = []

        def _load(host):
            seen.append(host)
            return "key-for-host"

        monkeypatch.setattr(key_store, "load_key_for", _load)
        assert (
            resolve_api_key(base_url="https://openrouter.ai/api/v1") == "key-for-host"
        )
        assert seen == ["openrouter.ai"]

    def test_env_fallback_only_for_groq_default(self, monkeypatch):
        monkeypatch.setattr(key_store, "load_key_for", lambda host: "")
        monkeypatch.setenv("GROQ_API_KEY", "env_key")
        assert resolve_api_key(base_url=DEFAULT_BASE_URL) == "env_key"
        assert resolve_api_key(base_url="https://openrouter.ai/api/v1") == ""


class TestDiscoverModels:
    def _client_factory(self, monkeypatch, ids=None, error=None):
        ids = ids if ids is not None else ["z/model", "a/model", "m/model"]

        class _ModelsApi:
            def list(self):
                if error is not None:
                    raise error
                return SimpleNamespace(
                    data=[SimpleNamespace(id=model_id) for model_id in ids]
                )

        class _Client:
            def __init__(self, base_url=None, api_key=None):
                self.models = _ModelsApi()

        monkeypatch.setattr(ai_engine, "OpenAI", _Client)

    def test_returns_sorted_models_and_host_message(self, monkeypatch):
        self._client_factory(monkeypatch)
        ok, msg, models = discover_models(
            api_key="sk-or-test", base_url="https://openrouter.ai/api/v1"
        )
        assert ok is True
        assert models == ["a/model", "m/model", "z/model"]
        assert "openrouter.ai" in msg
        assert "3 models available" in msg

    def test_model_must_be_in_catalog(self, monkeypatch):
        self._client_factory(monkeypatch)
        ok, msg, models = discover_models(
            api_key="sk-or-test",
            base_url="https://openrouter.ai/api/v1",
            model_id="missing/model",
        )
        assert ok is False
        assert models == []
        assert "missing/model" in msg
        assert "isn't available" in msg.lower()

    def test_empty_catalog_does_not_block(self, monkeypatch):
        self._client_factory(monkeypatch, ids=[])
        ok, msg, models = discover_models(
            api_key="sk-or-test", base_url="https://openrouter.ai/api/v1"
        )
        assert ok is True
        assert models == []
        assert "no models" in msg.lower()

    def test_auth_error_uses_specific_message(self, monkeypatch):
        self._client_factory(
            monkeypatch, error=RuntimeError("Error code: 401 - invalid_api_key")
        )
        ok, msg, models = discover_models(
            api_key="sk-bad", base_url="https://openrouter.ai/api/v1"
        )
        assert ok is False
        assert models == []
        assert "rejected" in msg.lower()
        assert "openrouter.ai" in msg


class TestDiscoveryPopulatesCombo:
    def test_check_loads_sorted_models_and_keeps_selection(self, panel, monkeypatch):
        calls: list = []

        def _discover(api_key=None, base_url=None, model_id=None):
            calls.append((api_key, base_url, model_id))
            return (
                True,
                "Connected to openrouter.ai — 3 models available.",
                ["z/model", "a/model", "m/model"],
            )

        monkeypatch.setattr(ai_engine, "discover_models", _discover)
        monkeypatch.setattr(settings_panel_module.threading, "Thread", _ImmediateThread)

        panel._api_base_url.setText("https://openrouter.ai/api/v1")
        panel._api_key.setText("sk-or-test")
        panel._ai_model.setCurrentIndex(-1)
        panel._ai_model.setEditText("a/model")

        panel._on_check_models()

        assert calls == [
            ("sk-or-test", "https://openrouter.ai/api/v1", "a/model")
        ]
        assert _combo_ids(panel) == ["a/model", "m/model", "z/model"]
        assert panel._selected_model() == "a/model"
        assert "3 models available" in panel._key_status.text()
        assert "#00FF88" in panel._key_status.styleSheet()

    def test_check_failure_shows_specific_error_and_keeps_combo(self, panel, monkeypatch):
        monkeypatch.setattr(
            ai_engine,
            "discover_models",
            lambda **kwargs: (
                False,
                "Your API key was rejected by openrouter.ai — paste it again "
                "from the provider's dashboard.",
                [],
            ),
        )
        monkeypatch.setattr(settings_panel_module.threading, "Thread", _ImmediateThread)
        before = _combo_ids(panel)

        panel._api_base_url.setText("https://openrouter.ai/api/v1")
        panel._api_key.setText("sk-bad")
        panel._on_check_models()

        assert _combo_ids(panel) == before
        assert "rejected" in panel._key_status.text().lower()
        assert "#FF5555" in panel._key_status.styleSheet()

    def test_invalid_url_fails_before_network(self, panel, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            ai_engine, "discover_models", lambda **kwargs: calls.append(kwargs)
        )

        panel._api_base_url.setText("api.groq.com/openai/v1")
        panel._on_check_models()

        assert calls == []
        assert "base url" in panel._key_status.text().lower()
        assert "#FF5555" in panel._key_status.styleSheet()

    def test_typed_model_survives_repopulation(self, panel):
        panel._ai_model.setCurrentIndex(-1)
        panel._ai_model.setEditText("acme/typed-model")

        panel._populate_model_combo(["a/model", "b/model"])

        assert "acme/typed-model" in _combo_ids(panel)
        assert panel._selected_model() == "acme/typed-model"


class TestSaveGate:
    def test_save_without_check_validates_and_saves(self, panel, monkeypatch):
        saved: list = []
        validation_calls: list = []
        save_calls: list = []

        def _validate(api_key=None, model_id=None, base_url=None):
            validation_calls.append((api_key, model_id, base_url))
            return True, "API key works - 'acme/model' is ready."

        monkeypatch.setattr(ai_engine, "validate_key_and_model", _validate)
        monkeypatch.setattr(settings_panel_module.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(
            key_store,
            "save_key_for",
            lambda host, key: save_calls.append((host, key)) or "keyring",
        )
        panel.saved.connect(saved.append)

        panel._api_base_url.setText("https://openrouter.ai/api/v1")
        panel._api_key.setText("sk-or-test")
        panel._ai_model.setCurrentIndex(-1)
        panel._ai_model.setEditText("acme/model")

        panel._emit_save()

        assert validation_calls == [
            ("sk-or-test", "acme/model", "https://openrouter.ai/api/v1")
        ]
        assert save_calls == [("openrouter.ai", "sk-or-test")]
        assert len(saved) == 1
        assert saved[0]["api_base_url"] == "https://openrouter.ai/api/v1"
        assert saved[0]["ai_model"] == "acme/model"

    def test_collect_and_apply_round_trip_base_url(self, panel):
        data = dict(BASE_SETTINGS)
        data["api_base_url"] = "https://openrouter.ai/api/v1"
        data["ai_model"] = "acme/model"
        data["custom_models"] = ["acme/model"]

        panel.apply_data(data)

        assert panel._api_base_url.text() == "https://openrouter.ai/api/v1"
        assert panel._selected_model() == "acme/model"
        collected = panel.collect_data()
        assert collected["api_base_url"] == "https://openrouter.ai/api/v1"
        assert collected["ai_model"] == "acme/model"

    def test_typed_model_is_persisted_in_custom_models(self, panel):
        panel._api_base_url.setText("https://openrouter.ai/api/v1")
        panel._ai_model.setCurrentIndex(-1)
        panel._ai_model.setEditText("acme/custom")

        collected = panel.collect_data()

        assert collected["ai_model"] == "acme/custom"
        assert "acme/custom" in collected["custom_models"]


class TestKeyStatusPerHost:
    def test_status_reflects_current_base_url(self, panel, monkeypatch):
        monkeypatch.setattr(
            key_store, "load_key_for", lambda host: "sk" if host == "openrouter.ai" else ""
        )

        panel._api_base_url.setText("https://openrouter.ai/api/v1")
        panel._on_base_url_edited()

        assert "openrouter.ai" in panel._key_status.text()
        assert "Key stored" in panel._key_status.text()

        panel._api_base_url.setText("https://api.groq.com/openai/v1")
        panel._on_base_url_edited()

        assert "No key stored" in panel._key_status.text()
