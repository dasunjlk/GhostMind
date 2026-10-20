"""Tests for rate-limit detection and backoff helpers in core/ai_engine.py."""
from __future__ import annotations

from core.ai_engine import _is_rate_limit_error, _rate_limit_backoff


class _FakeResponse:
    def __init__(self, status_code=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class TestRateLimitDetection:
    def test_detects_429_in_message(self):
        assert _is_rate_limit_error(RuntimeError("Error code: 429 - too many requests"))

    def test_detects_rate_limit_text(self):
        assert _is_rate_limit_error(RuntimeError("Rate limit exceeded"))

    def test_detects_status_code(self):
        err = RuntimeError("request failed")
        err.response = _FakeResponse(status_code=429)
        assert _is_rate_limit_error(err)

    def test_ignores_other_errors(self):
        assert not _is_rate_limit_error(RuntimeError("connection refused"))
        assert not _is_rate_limit_error(RuntimeError("model_not_found"))


class TestBackoffDelay:
    def test_exponential_delays(self):
        assert _rate_limit_backoff(RuntimeError("429"), 1) == 1.0
        assert _rate_limit_backoff(RuntimeError("429"), 2) == 2.0
        assert _rate_limit_backoff(RuntimeError("429"), 3) == 4.0

    def test_capped_at_30s(self):
        assert _rate_limit_backoff(RuntimeError("429"), 10) == 30.0

    def test_honors_retry_after_header(self):
        err = RuntimeError("429")
        err.response = _FakeResponse(headers={"retry-after": "17"})
        assert _rate_limit_backoff(err, 1) == 17.0

    def test_retry_after_is_also_capped(self):
        err = RuntimeError("429")
        err.response = _FakeResponse(headers={"retry-after": "90"})
        assert _rate_limit_backoff(err, 1) == 30.0

    def test_invalid_retry_after_falls_back(self):
        err = RuntimeError("429")
        err.response = _FakeResponse(headers={"retry-after": "soon"})
        assert _rate_limit_backoff(err, 2) == 2.0
