"""Tests for the provider-agnostic OpenAI-compatible engine (C1).

No network, no real SDK client, no Qt event loop: clients are faked and worker
signals are delivered directly.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import core.ai_engine as ai_engine
from core.ai_engine import (
    DEFAULT_BASE_URL,
    DETERMINISTIC_SEED,
    DETERMINISTIC_TEMPERATURE,
    AiStreamWorker,
    _classify_api_error,
    _get_client,
    _models_to_try,
    validate_key_and_model,
)


class _FakeResponse:
    def __init__(self, status_code=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


def _http_error(message: str, status: int) -> RuntimeError:
    err = RuntimeError(message)
    err.status_code = status
    err.response = _FakeResponse(status_code=status)
    return err


class TestClientConstruction:
    def test_custom_base_url_and_key_are_passed_to_sdk(self, monkeypatch):
        seen = {}

        class _FakeOpenAI:
            def __init__(self, base_url=None, api_key=None):
                seen["base_url"] = base_url
                seen["api_key"] = api_key

        monkeypatch.setattr(ai_engine, "OpenAI", _FakeOpenAI)
        _get_client("https://openrouter.ai/api/v1", "sk-or-test")
        assert seen == {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-test",
        }

    def test_defaults_to_groq_base_url(self, monkeypatch):
        seen = {}

        class _FakeOpenAI:
            def __init__(self, base_url=None, api_key=None):
                seen["base_url"] = base_url

        monkeypatch.setattr(ai_engine, "OpenAI", _FakeOpenAI)
        _get_client(api_key="gsk_test")
        assert seen["base_url"] == DEFAULT_BASE_URL

    def test_invalid_url_is_rejected_before_network(self, monkeypatch):
        monkeypatch.setattr(ai_engine, "OpenAI", object)
        with pytest.raises(RuntimeError) as exc:
            _get_client("api.groq.com/openai/v1", "gsk_test")
        assert "base url" in str(exc.value).lower()

    def test_trailing_slash_is_removed(self, monkeypatch):
        seen = {}

        class _FakeOpenAI:
            def __init__(self, base_url=None, api_key=None):
                seen["base_url"] = base_url

        monkeypatch.setattr(ai_engine, "OpenAI", _FakeOpenAI)
        _get_client("https://openrouter.ai/api/v1/", "sk")
        assert seen["base_url"] == "https://openrouter.ai/api/v1"


class TestErrorTaxonomy:
    def test_401_and_403_are_key_errors(self):
        for status in (401, 403):
            msg = _classify_api_error(
                _http_error("unauthorized", status),
                base_url="https://openrouter.ai/api/v1",
            )
            assert "rejected" in msg.lower()
            assert "openrouter.ai" in msg

    def test_402_is_no_credit(self):
        msg = _classify_api_error(
            _http_error("payment required", 402),
            base_url="https://openrouter.ai/api/v1",
        )
        assert "no credit" in msg.lower()

    def test_429_is_rate_limit(self):
        msg = _classify_api_error(_http_error("too many requests", 429))
        assert "rate limit" in msg.lower()

    def test_model_404_is_model_specific(self):
        msg = _classify_api_error(
            _http_error("model_not_found", 404),
            base_url="https://openrouter.ai/api/v1",
            model_id="acme/missing",
        )
        assert "acme/missing" in msg
        assert "isn't available" in msg.lower()

    def test_generic_404_points_at_the_base_url(self):
        msg = _classify_api_error(
            _http_error("Not Found", 404),
            base_url="https://openrouter.ai/api/v1",
            model_id="acme/missing",
        )
        assert "base url" in msg.lower()
        assert "isn't available" not in msg.lower()

    def test_5xx_is_server_error(self):
        msg = _classify_api_error(
            _http_error("bad gateway", 502),
            base_url="https://openrouter.ai/api/v1",
        )
        assert "server error" in msg.lower()

    def test_connection_error_mentions_base_url(self):
        msg = _classify_api_error(
            ConnectionError("getaddrinfo failed"),
            base_url="https://openrouter.ai/api/v1",
        )
        assert "couldn't reach" in msg.lower()
        assert "base url" in msg.lower()


class TestValidationWithCustomProvider:
    def test_models_list_uses_the_requested_base_url(self, monkeypatch):
        seen = {}

        class _Client:
            def __init__(self, base_url=None, api_key=None):
                seen["base_url"] = base_url
                self.models = SimpleNamespace(
                    list=lambda: SimpleNamespace(
                        data=[SimpleNamespace(id="acme/model")]
                    )
                )

        monkeypatch.setattr(ai_engine, "OpenAI", _Client)
        ok, msg = validate_key_and_model(
            api_key="sk-or-test",
            model_id="acme/model",
            base_url="https://openrouter.ai/api/v1",
        )
        assert ok is True
        assert "ready" in msg.lower()
        assert seen["base_url"] == "https://openrouter.ai/api/v1"


class TestGenerateAnswer:
    def test_uses_deterministic_settings(self, monkeypatch):
        client = _FakeClient(fallback_text="answer")
        monkeypatch.setattr(
            ai_engine,
            "_get_client",
            lambda base_url=None, api_key=None: client,
        )
        result = asyncio.run(
            ai_engine.generate_answer(
                "What is 2+2?",
                "manual",
                base_url="https://openrouter.ai/api/v1",
                api_key="sk",
            )
        )
        assert result == "answer"
        call = client.calls[0]
        assert call["temperature"] == DETERMINISTIC_TEMPERATURE
        assert call["seed"] == DETERMINISTIC_SEED
        assert call["model"] == ai_engine.MODEL_ID

    def test_custom_provider_does_not_use_groq_backups(self, monkeypatch):
        client = _FakeClient(error=_http_error("model_not_found", 404))
        monkeypatch.setattr(
            ai_engine,
            "_get_client",
            lambda base_url=None, api_key=None: client,
        )
        with pytest.raises(RuntimeError):
            asyncio.run(
                ai_engine.generate_answer(
                    "What is 2+2?",
                    "manual",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="sk",
                )
            )
        assert [call["model"] for call in client.calls] == [ai_engine.MODEL_ID]


class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.calls.append(kwargs)
        if self.owner.error is not None:
            raise self.owner.error
        if kwargs.get("stream"):
            if self.owner.stream is not None:
                return self.owner.stream
            return iter(self.owner.chunks)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.owner.fallback_text)
                )
            ]
        )


class _FakeClient:
    def __init__(self, chunks=None, stream=None, error=None, fallback_text="fallback"):
        self.calls = []
        self.chunks = chunks or []
        self.stream = stream
        self.error = error
        self.fallback_text = fallback_text
        self.chat = SimpleNamespace(completions=_Completions(self))


def _run_worker(
    monkeypatch,
    client,
    base_url=None,
    api_key="sk-test",
    history=None,
    sleep=None,
):
    monkeypatch.setattr(
        ai_engine,
        "_get_client",
        lambda base_url=None, api_key=None: client,
    )
    monkeypatch.setattr(ai_engine.time, "sleep", sleep or (lambda _seconds: None))
    worker = AiStreamWorker(
        "What is 2+2?",
        "manual",
        base_url=base_url,
        api_key=api_key,
        history=history,
    )
    chunks = []
    failures = []
    finished = []
    worker.chunk_received.connect(chunks.append)
    worker.failed.connect(failures.append)
    worker.finished_ok.connect(lambda: finished.append(True))
    worker.run()
    return chunks, failures, finished


class TestStreamWorker:
    def test_streams_with_deterministic_settings(self, monkeypatch):
        client = _FakeClient(chunks=[_Chunk("4")])
        chunks, failures, finished = _run_worker(
            monkeypatch,
            client,
            base_url="https://openrouter.ai/api/v1",
        )
        assert chunks == ["4"]
        assert failures == []
        assert finished == [True]
        call = client.calls[0]
        assert call["model"] == ai_engine.MODEL_ID
        assert call["temperature"] == DETERMINISTIC_TEMPERATURE
        assert call["seed"] == DETERMINISTIC_SEED

    def test_history_is_inserted_before_the_current_user_message(self, monkeypatch):
        client = _FakeClient(chunks=[_Chunk("4")])
        _run_worker(
            monkeypatch,
            client,
            history=[
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
            ],
        )

        messages = client.calls[0]["messages"]
        assert [message["role"] for message in messages] == [
            "system",
            "user",
            "assistant",
            "user",
        ]
        assert messages[1]["content"] == "first question"
        assert messages[2]["content"] == "first answer"
        assert messages[3]["content"] == "What is 2+2?"

    def test_history_entries_are_filtered(self, monkeypatch):
        client = _FakeClient(chunks=[_Chunk("4")])
        _run_worker(
            monkeypatch,
            client,
            history=[
                "not a message",
                {"role": "system", "content": "ignored"},
                {"role": "user", "content": "   "},
                {"role": "assistant", "content": "kept"},
            ],
        )

        messages = client.calls[0]["messages"]
        assert [message["role"] for message in messages] == [
            "system",
            "assistant",
            "user",
        ]
        assert messages[1]["content"] == "kept"

    def test_custom_provider_does_not_fall_back(self, monkeypatch):
        client = _FakeClient(error=_http_error("model_not_found", 404))
        _chunks, failures, _finished = _run_worker(
            monkeypatch,
            client,
            base_url="https://openrouter.ai/api/v1",
        )
        assert [call["model"] for call in client.calls] == [ai_engine.MODEL_ID]
        assert failures
        assert "isn't available" in failures[0].lower()

    def test_groq_default_tries_backup_models(self, monkeypatch):
        client = _FakeClient(error=_http_error("model_not_found", 404))
        _chunks, failures, _finished = _run_worker(
            monkeypatch,
            client,
            base_url=DEFAULT_BASE_URL,
        )
        expected = _models_to_try(ai_engine.MODEL_ID, DEFAULT_BASE_URL)
        assert [call["model"] for call in client.calls] == expected
        assert failures

    def test_mid_stream_failure_uses_non_streaming_fallback(self, monkeypatch):
        def _broken_stream():
            yield _Chunk("partial")
            raise RuntimeError("connection reset")

        client = _FakeClient(stream=_broken_stream(), fallback_text="complete")
        chunks, failures, finished = _run_worker(
            monkeypatch,
            client,
            base_url="https://openrouter.ai/api/v1",
        )
        assert chunks == ["partial", "complete"]
        assert failures == []
        assert finished == [True]
        fallback_call = client.calls[1]
        assert "stream" not in fallback_call
        assert fallback_call["temperature"] == DETERMINISTIC_TEMPERATURE
        assert fallback_call["seed"] == DETERMINISTIC_SEED

    def test_auth_failure_emits_specific_message(self, monkeypatch):
        client = _FakeClient(error=_http_error("unauthorized", 401))
        _chunks, failures, _finished = _run_worker(
            monkeypatch,
            client,
            base_url="https://openrouter.ai/api/v1",
        )
        assert failures
        assert "rejected" in failures[0].lower()
        assert "openrouter.ai" in failures[0]
        assert len(client.calls) == 1

    def test_no_credit_failure_emits_specific_message(self, monkeypatch):
        client = _FakeClient(error=_http_error("payment required", 402))
        _chunks, failures, _finished = _run_worker(
            monkeypatch,
            client,
            base_url="https://openrouter.ai/api/v1",
        )
        assert failures
        assert "no credit" in failures[0].lower()
        assert len(client.calls) == 1

    def test_rate_limit_retries_then_streams(self, monkeypatch):
        calls = []

        class _Completions:
            def create(self, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    raise _http_error("rate limit", 429)
                return iter([_Chunk("ok")])

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=_Completions())
        )
        chunks, failures, finished = _run_worker(
            monkeypatch,
            client,
            base_url="https://openrouter.ai/api/v1",
        )
        assert chunks == ["ok"]
        assert failures == []
        assert finished == [True]
        assert len(calls) == 2
        assert calls[1]["seed"] == DETERMINISTIC_SEED

    def test_rate_limit_backoff_is_capped_per_model(self, monkeypatch):
        sleeps: list[float] = []
        err = _http_error("rate limit", 429)
        err.response.headers["retry-after"] = "17"
        client = _FakeClient(error=err)

        chunks, failures, _finished = _run_worker(
            monkeypatch,
            client,
            base_url="https://openrouter.ai/api/v1",
            sleep=sleeps.append,
        )

        assert sum(sleeps) <= ai_engine.MAX_MODEL_BACKOFF_SECONDS
        assert sleeps == [ai_engine.MAX_MODEL_BACKOFF_SECONDS]
        assert any("rate limited, retrying" in chunk for chunk in chunks)
        assert failures
