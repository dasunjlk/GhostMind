"""Tests for utils/error_reporter.py — scrubbing, gating, and Sentry wiring.

All tests are offline: a fake in-memory Transport stands in for the HTTP
transport, so no event ever leaves the process.
"""
from __future__ import annotations

import json
import logging
import os
import socket

import pytest
import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

import utils.error_reporter as error_reporter
from version import __version__

TEST_DSN = "https://public@example.com/1"


class FakeTransport(Transport):
    """Collects envelopes in memory instead of sending them."""

    def __init__(self, options=None):
        super().__init__(options)
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)


def _enable(monkeypatch, transport):
    """Force-enable the reporter and route SDK sends into the fake transport."""
    monkeypatch.setenv(error_reporter.ENV_FORCE_TELEMETRY, "1")
    monkeypatch.setenv(error_reporter.ENV_DSN, TEST_DSN)
    real_init = sentry_sdk.init

    def spy_init(*args, **kwargs):
        kwargs["transport"] = transport
        return real_init(*args, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", spy_init)


def _event_from(transport) -> dict:
    assert transport.envelopes, "expected at least one captured envelope"
    restored = Envelope.deserialize(transport.envelopes[-1].serialize())
    payload = restored.items[0].payload
    if hasattr(payload, "get_bytes"):
        return json.loads(payload.get_bytes().decode("utf-8"))
    if isinstance(payload, (bytes, bytearray)):
        return json.loads(bytes(payload).decode("utf-8"))
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def _blob(transport) -> str:
    return b"".join(env.serialize() for env in transport.envelopes).decode("utf-8", "replace")


@pytest.fixture(autouse=True)
def _isolate_sdk():
    error_reporter.reset()
    yield
    error_reporter.reset()
    try:
        sentry_sdk.get_global_scope().clear()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# scrub_text
# --------------------------------------------------------------------------- #

class TestScrubText:
    def test_redacts_user_paths(self):
        text = r"open C:\Users\JohnDoe\secret.txt and C:/Users/JohnDoe/app.txt"
        out = error_reporter.scrub_text(text)
        assert "JohnDoe" not in out
        assert r"C:\Users\<user>\secret.txt" in out

    def test_redacts_api_keys(self):
        text = "key gsk_A1b2C3d4E5f6G7h8 and sk-1234567890abcdef"
        out = error_reporter.scrub_text(text)
        assert "gsk_A1b2C3d4E5f6G7h8" not in out
        assert "sk-1234567890abcdef" not in out
        assert out.count("***") == 2

    def test_redacts_secret_assignments(self):
        text = "api_key=SUPERSECRET42 token: abcdef123456 password=hunter2"
        out = error_reporter.scrub_text(text)
        assert "SUPERSECRET42" not in out
        assert "abcdef123456" not in out
        assert "hunter2" not in out

    def test_redacts_identity_needles_case_insensitive(self):
        out = error_reporter.scrub_text(
            "host DESKTOP-ABC123 user: SomeUserName", ["desktop-abc123", "someusername"]
        )
        assert "DESKTOP-ABC123" not in out
        assert "SomeUserName" not in out

    def test_empty_passthrough(self):
        assert error_reporter.scrub_text("") == ""
        assert error_reporter.scrub_text(None) is None


# --------------------------------------------------------------------------- #
# _scrub_event
# --------------------------------------------------------------------------- #

class TestScrubEvent:
    def test_drops_sentry_internal_logger(self):
        event = {"logger": "sentry_sdk.errors", "message": "Failed to send"}
        assert error_reporter._scrub_event(event, None, []) is None

    def test_strips_server_name_and_keeps_only_user_id(self):
        event = {
            "server_name": "DESKTOP-SECRET",
            "user": {"id": "abc-123", "username": "bob", "ip_address": "1.2.3.4"},
            "request": {"url": "https://private"},
            "message": "hi",
        }
        out = error_reporter._scrub_event(event, None, [])
        assert "server_name" not in out
        assert "request" not in out
        assert out["user"] == {"id": "abc-123"}

    def test_scrubs_exception_frames_and_drops_context(self):
        event = {
            "exception": {
                "values": [
                    {
                        "value": r"failed for C:\Users\Jane\data on HOSTX",
                        "stacktrace": {
                            "frames": [
                                {
                                    "filename": r"C:\Users\Jane\app\main.py",
                                    "abs_path": r"C:\Users\Jane\app\main.py",
                                    "context_line": "secret_sauce = api_key",
                                    "pre_context": ["api_key = 'leaked'"],
                                    "post_context": ["pass"],
                                    "vars": {"transcript": "user said something private"},
                                }
                            ]
                        },
                    }
                ]
            }
        }
        out = error_reporter._scrub_event(event, None, ["hostx"])
        value = out["exception"]["values"][0]["value"]
        assert "Jane" not in value
        assert "HOSTX" not in value
        frame = out["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert "Jane" not in frame["filename"]
        for key in ("vars", "context_line", "pre_context", "post_context"):
            assert key not in frame

    def test_clips_long_messages(self):
        out = error_reporter._scrub_event({"message": "x" * 5000}, None, [])
        assert "[truncated" in out["message"]
        assert len(out["message"]) < 5000

    def test_never_raises_on_weird_input(self):
        assert error_reporter._scrub_event({}, None, []) == {}
        assert error_reporter._scrub_event({"exception": "nope"}, None, []) is not None


# --------------------------------------------------------------------------- #
# Anonymous install id
# --------------------------------------------------------------------------- #

class TestInstallId:
    def test_created_and_stable(self, tmp_path):
        first = error_reporter.load_or_create_install_id(tmp_path)
        second = error_reporter.load_or_create_install_id(tmp_path)
        assert first
        assert first == second
        assert (tmp_path / "config" / error_reporter.ID_FILENAME).is_file()


# --------------------------------------------------------------------------- #
# Gating
# --------------------------------------------------------------------------- #

class TestGating:
    def test_disabled_without_dsn(self, monkeypatch, tmp_path):
        monkeypatch.setenv(error_reporter.ENV_FORCE_TELEMETRY, "1")
        monkeypatch.delenv(error_reporter.ENV_DSN, raising=False)
        monkeypatch.setattr(error_reporter, "SENTRY_DSN", "")
        assert error_reporter.install(tmp_path) is False

    def test_no_telemetry_env_wins_over_force(self, monkeypatch, tmp_path):
        monkeypatch.setenv(error_reporter.ENV_FORCE_TELEMETRY, "1")
        monkeypatch.setenv(error_reporter.ENV_DSN, TEST_DSN)
        monkeypatch.setenv(error_reporter.ENV_NO_TELEMETRY, "1")
        assert error_reporter.install(tmp_path) is False

    def test_disabled_under_pytest_by_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv(error_reporter.ENV_FORCE_TELEMETRY, raising=False)
        monkeypatch.setenv(error_reporter.ENV_DSN, TEST_DSN)
        assert error_reporter.install(tmp_path) is False

    def test_flush_without_sdk_is_noop(self):
        error_reporter.flush(timeout=0.1)


# --------------------------------------------------------------------------- #
# End-to-end wiring (fake transport, real SDK)
# --------------------------------------------------------------------------- #

class TestWiring:
    def test_error_log_sends_scrubbed_event(self, monkeypatch, tmp_path):
        transport = FakeTransport()
        _enable(monkeypatch, transport)
        assert error_reporter.install(tmp_path) is True

        host = socket.gethostname()
        secret_key = "gsk_A1b2C3d4E5f6G7h8I9j0"
        logging.getLogger("core.test_wiring").error(
            "Failed to open C:\\Users\\TestUser99\\file.txt on %s (key=%s)", host, secret_key
        )
        error_reporter.flush(timeout=5)

        event = _event_from(transport)
        assert event["release"] == f"ghostmind@{__version__}"
        assert event["environment"] == "development"
        assert "server_name" not in event
        blob = json.dumps(event)
        assert "TestUser99" not in blob
        assert secret_key not in blob
        assert "<user>" in blob
        if len(host) >= 3:
            assert host.lower() not in blob.lower()
        install_id = (tmp_path / "config" / error_reporter.ID_FILENAME).read_text(
            encoding="utf-8"
        ).strip()
        assert event["user"]["id"] == install_id

    def test_local_variables_are_not_sent(self, monkeypatch, tmp_path):
        transport = FakeTransport()
        _enable(monkeypatch, transport)
        assert error_reporter.install(tmp_path) is True

        secret = "SECRET_LOCAL_VALUE_123456"

        def _boom():
            private_local = secret  # noqa: F841
            raise ValueError("boom")

        try:
            _boom()
        except ValueError:
            sentry_sdk.capture_exception()
        error_reporter.flush(timeout=5)

        assert secret not in _blob(transport)

    def test_no_telemetry_env_means_no_events(self, monkeypatch, tmp_path):
        transport = FakeTransport()
        _enable(monkeypatch, transport)
        monkeypatch.setenv(error_reporter.ENV_NO_TELEMETRY, "1")
        assert error_reporter.install(tmp_path) is False
        logging.getLogger("core.test_wiring").error("should not be sent")
        error_reporter.flush(timeout=2)
        assert transport.envelopes == []

    def test_second_install_is_idempotent(self, monkeypatch, tmp_path):
        transport = FakeTransport()
        _enable(monkeypatch, transport)
        assert error_reporter.install(tmp_path) is True
        assert error_reporter.install(tmp_path) is True

    def test_test_error_hook_sends_synthetic_error(self, monkeypatch, tmp_path):
        transport = FakeTransport()
        _enable(monkeypatch, transport)
        monkeypatch.setenv(error_reporter.ENV_TEST_ERROR, "1")
        assert error_reporter.install(tmp_path) is True
        assert transport.envelopes, "QA hook should have sent a synthetic error"
        assert "synthetic error" in _blob(transport)

    def test_username_never_leaks_through_install(self, monkeypatch, tmp_path):
        transport = FakeTransport()
        _enable(monkeypatch, transport)
        assert error_reporter.install(tmp_path) is True

        username = os.environ.get("USERNAME", "")
        logging.getLogger("core.test_wiring").error("user context probe")
        error_reporter.flush(timeout=5)

        if len(username) >= 3 and username.lower() not in error_reporter.GENERIC_ACCOUNTS:
            assert username.lower() not in _blob(transport).lower()
