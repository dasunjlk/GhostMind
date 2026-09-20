"""Tests for ai_engine key/model validation (validate_key_and_model).

Pure logic tests: the Groq client is faked, no network, no Qt.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.ai_engine as ai_engine
from core.ai_engine import (
    ADD_CUSTOM_MODEL_SENTINEL,
    _classify_api_error,
    resolve_api_key,
    validate_key_and_model,
)


class _FakeModels:
    def __init__(self, ids):
        self.data = [SimpleNamespace(id=i) for i in ids]


def _make_client_factory(monkeypatch, ids=None, error: Exception | None = None):
    """Patch core.ai_engine.Groq with a fake whose models.list behaves as given."""
    ids = ids if ids is not None else ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]

    class _ModelsApi:
        def list(self):
            if error is not None:
                raise error
            return _FakeModels(ids)

    class _Client:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.models = _ModelsApi()

    monkeypatch.setattr(ai_engine, "Groq", _Client)
    return _Client


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


class TestValidateNoKey:
    def test_no_key_anywhere(self, monkeypatch):
        monkeypatch.setattr(ai_engine, "resolve_api_key", lambda explicit="": "")
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
        assert "network" in msg.lower() or "internet" in msg.lower()


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
        assert "not available" in msg.lower()
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

    def test_groq_not_installed(self, monkeypatch):
        monkeypatch.setattr(ai_engine, "Groq", None)
        monkeypatch.setattr(ai_engine, "resolve_api_key", lambda explicit="": "gsk_ok")
        ok, msg = validate_key_and_model()
        assert ok is False
        assert "pip install groq" in msg


class TestClassifyApiError:
    def test_401(self):
        msg = _classify_api_error(RuntimeError("Error code: 401 - {'error': 'invalid api key'}"))
        assert "rejected" in msg.lower()

    def test_timeout(self):
        msg = _classify_api_error(RuntimeError("The read operation timed out"))
        assert "network" in msg.lower()

    def test_other_error_includes_detail(self):
        msg = _classify_api_error(RuntimeError("Error code: 413 - payload too large"))
        assert "Groq error" in msg
        assert "413" in msg


class TestResolveApiKey:
    def test_explicit_beats_everything(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "env_key")
        assert resolve_api_key(" explicit_key ") == "explicit_key"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "env_key")
        assert resolve_api_key() == "env_key"

    def test_empty_string_means_lookup(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "env_key")
        assert resolve_api_key("   ") == "env_key"


class TestSentinel:
    def test_sentinel_is_not_a_real_model(self):
        assert ADD_CUSTOM_MODEL_SENTINEL not in [m for m, _ in ai_engine.AVAILABLE_MODELS]
