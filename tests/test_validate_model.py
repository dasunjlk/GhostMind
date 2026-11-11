"""Tests for ai_engine key/model validation (validate_key_and_model).

Pure logic tests: the OpenAI-compatible client is faked, no network, no Qt.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.ai_engine as ai_engine
from core.ai_engine import (
    DEFAULT_BASE_URL,
    _classify_api_error,
    resolve_api_key,
    validate_key_and_model,
)


class _FakeModels:
    def __init__(self, ids):
        self.data = [SimpleNamespace(id=i) for i in ids]


def _make_client_factory(monkeypatch, ids=None, error: Exception | None = None):
    """Patch core.ai_engine.OpenAI with a fake whose models.list behaves as given."""
    ids = ids if ids is not None else ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]

    class _ModelsApi:
        def list(self):
            if error is not None:
                raise error
            return _FakeModels(ids)

    class _Client:
        def __init__(self, base_url=None, api_key=None):
            self.base_url = base_url
            self.api_key = api_key
            self.models = _ModelsApi()

    monkeypatch.setattr(ai_engine, "OpenAI", _Client)
    return _Client


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


class TestValidateNoKey:
    def test_no_key_anywhere(self, monkeypatch):
        monkeypatch.setattr(
            ai_engine, "resolve_api_key", lambda explicit=None, base_url=None: ""
        )
        ok, msg = validate_key_and_model()
        assert ok is False
        assert "Settings" in msg or "console.groq.com" in msg


class TestValidateKeyRejected:
    def test_401_key_rejected(self, monkeypatch):
        _make_client_factory(
            monkeypatch, error=RuntimeError("Error code: 401 - invalid_api_key")
        )
        ok, msg = validate_key_and_model(api_key="gsk_bad", model_id="qwen/qwen3.8-27b")
        assert ok is False
        assert "rejected" in msg.lower() or "invalid" in msg.lower()

    def test_network_error(self, monkeypatch):
        _make_client_factory(monkeypatch, error=ConnectionError("getaddrinfo failed"))
        ok, msg = validate_key_and_model(api_key="gsk_ok", model_id="qwen/qwen3.8-27b")
        assert ok is False
        assert "couldn't reach" in msg.lower() or "base url" in msg.lower()


class TestValidateModelMatch:
    def test_model_available(self, monkeypatch):
        _make_client_factory(monkeypatch)
        ok, msg = validate_key_and_model(api_key="gsk_ok", model_id="qwen/qwen3.8-27b")
        assert ok is True
        assert "ready" in msg.lower()

    def test_model_not_in_key_catalog(self, monkeypatch):
        _make_client_factory(monkeypatch)
        ok, msg = validate_key_and_model(
            api_key="gsk_ok", model_id="llama-3.3-70b-versatile"
        )
        assert ok is False
        assert "isn't available" in msg.lower()
        assert "llama-3.3-70b-versatile" in msg

    def test_empty_catalog_means_no_model_check(self, monkeypatch):
        # Some deployments return no list; never block on that.
        _make_client_factory(monkeypatch, ids=[])
        ok, _msg = validate_key_and_model(api_key="gsk_ok", model_id="anything/here")
        assert ok is True

    def test_custom_model_id_accepted_when_listed(self, monkeypatch):
        _make_client_factory(
            monkeypatch, ids=["qwen/qwen3.8-27b", "my-org/my-fine-tune"]
        )
        ok, _msg = validate_key_and_model(api_key="gsk_ok", model_id="my-org/my-fine-tune")
        assert ok is True

    def test_openai_not_installed(self, monkeypatch):
        monkeypatch.setattr(ai_engine, "OpenAI", None)
        monkeypatch.setattr(
            ai_engine, "resolve_api_key", lambda explicit=None, base_url=None: "gsk_ok"
        )
        ok, msg = validate_key_and_model()
        assert ok is False
        assert "pip install openai" in msg


class TestClassifyApiError:
    def test_401(self):
        msg = _classify_api_error(RuntimeError("Error code: 401 - {'error': 'invalid api key'}"))
        assert "rejected" in msg.lower()

    def test_timeout(self):
        msg = _classify_api_error(RuntimeError("The read operation timed out"))
        assert "couldn't reach" in msg.lower() or "base url" in msg.lower()

    def test_other_error_includes_detail(self):
        msg = _classify_api_error(RuntimeError("Error code: 413 - payload too large"))
        assert msg == "api.groq.com error: Error code: 413 - payload too large"
        assert "413" in msg


class TestResolveApiKey:
    @pytest.fixture(autouse=True)
    def _no_stored_key(self, monkeypatch):
        """Keep tests off the developer's real Windows Credential Manager key."""
        import utils.key_store

        monkeypatch.setattr(utils.key_store, "load_key_for", lambda host: "")

    def test_explicit_beats_everything(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "env_key")
        assert resolve_api_key(" explicit_key ") == "explicit_key"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "env_key")
        assert resolve_api_key() == "env_key"

    def test_empty_string_means_lookup(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "env_key")
        assert resolve_api_key("   ") == "env_key"

    def test_env_fallback_is_scoped_to_groq_default(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "env_key")
        assert resolve_api_key(base_url=DEFAULT_BASE_URL) == "env_key"
        assert resolve_api_key(base_url="https://openrouter.ai/api/v1") == ""
