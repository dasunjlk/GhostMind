"""Tests for utils/key_store.py — API key storage (keyring + plaintext fallback)."""
from __future__ import annotations

import toml
import pytest

import utils.key_store as key_store


class _FakeKeyring:
    """Minimal in-memory stand-in for the keyring module."""

    def __init__(self) -> None:
        self._store: dict = {}
        self.fail_get = False
        self.fail_set = False

    def get_password(self, service: str, name: str):
        if self.fail_get:
            raise RuntimeError("backend read error")
        return self._store.get((service, name))

    def set_password(self, service: str, name: str, secret: str) -> None:
        if self.fail_set:
            raise RuntimeError("backend write error")
        self._store[(service, name)] = secret

    def delete_password(self, service: str, name: str) -> None:
        self._store.pop((service, name), None)


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch, tmp_path):
    """Route key_store at an in-memory keyring and a temp fallback file."""
    fake = _FakeKeyring()
    monkeypatch.setattr(key_store, "_KEYRING", fake, raising=False)
    monkeypatch.setattr(key_store, "_fallback_path", lambda: tmp_path / "settings.toml")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return fake


def _fallback_toml(tmp_path):
    path = tmp_path / "settings.toml"
    if not path.is_file():
        return {}
    return toml.load(path) or {}


class TestKeyringBackend:
    def test_save_and_load_roundtrip(self, tmp_path):
        assert key_store.save_key("gsk_abc123") == "keyring"
        assert key_store.load_key() == "gsk_abc123"

    def test_save_strips_whitespace(self, tmp_path):
        key_store.save_key("   gsk_xyz   ")
        assert key_store.load_key() == "gsk_xyz"

    def test_save_overwrites_previous(self, tmp_path):
        key_store.save_key("gsk_old")
        key_store.save_key("gsk_new")
        assert key_store.load_key() == "gsk_new"

    def test_save_does_not_touch_settings_toml(self, tmp_path):
        key_store.save_key("gsk_secret")
        data = _fallback_toml(tmp_path)
        assert "key_storage" not in data

    def test_save_removes_stale_plaintext_copy(self, tmp_path):
        key_store._write_fallback("gsk_leaked")
        assert key_store.load_key() == "gsk_leaked"
        key_store.save_key("gsk_secure")
        data = _fallback_toml(tmp_path)
        assert "key_storage" not in data
        assert key_store.load_key() == "gsk_secure"

    def test_load_missing_returns_empty(self):
        assert key_store.load_key() == ""

    def test_key_is_stored_reflects_state(self):
        assert key_store.key_is_stored() is False
        key_store.save_key("gsk_here")
        assert key_store.key_is_stored() is True

    def test_clear_removes_key(self):
        key_store.save_key("gsk_bye")
        key_store.clear_key()
        assert key_store.load_key() == ""
        assert key_store.key_is_stored() is False

    def test_clear_with_nothing_stored_is_safe(self):
        key_store.clear_key()  # must not raise
        assert key_store.load_key() == ""

    def test_save_empty_key_clears(self):
        key_store.save_key("gsk_temp")
        key_store.save_key("")
        assert key_store.load_key() == ""


class TestPlaintextFallback:
    """keyring unavailable -> settings.toml [key_storage] tradeoff."""

    @pytest.fixture(autouse=True)
    def no_keyring(self, monkeypatch):
        monkeypatch.setattr(key_store, "_KEYRING", False, raising=False)

    def test_save_reports_plaintext(self, tmp_path):
        assert key_store.save_key("gsk_plain") == "plaintext"

    def test_roundtrip_without_keyring(self, tmp_path):
        key_store.save_key("gsk_plain")
        assert key_store.load_key() == "gsk_plain"

    def test_fallback_written_to_settings_toml(self, tmp_path):
        key_store.save_key("gsk_plain")
        data = _fallback_toml(tmp_path)
        assert data["key_storage"]["api_key"] == "gsk_plain"

    def test_clear_removes_fallback_section(self, tmp_path):
        key_store.save_key("gsk_plain")
        key_store.clear_key()
        data = _fallback_toml(tmp_path)
        assert "key_storage" not in data

    def test_preserves_other_settings(self, tmp_path):
        path = tmp_path / "settings.toml"
        path.write_text('ai_model = "qwen/qwen3.8-27b"\nopacity = 0.9\n', encoding="utf-8")
        key_store.save_key("gsk_keep")
        data = toml.load(path)
        assert data["ai_model"] == "qwen/qwen3.8-27b"
        assert data["opacity"] == 0.9
        assert data["key_storage"]["api_key"] == "gsk_keep"

    def test_is_keyring_available_false(self):
        assert key_store.is_keyring_available() is False


class TestKeyringFailures:
    def test_write_failure_falls_back_to_plaintext(self, tmp_path, fake_keyring):
        fake_keyring.fail_set = True
        assert key_store.save_key("gsk_fallback") == "plaintext"
        assert key_store.load_key() == "gsk_fallback"

    def test_read_failure_still_finds_plaintext(self, tmp_path, fake_keyring):
        key_store._write_fallback("gsk_hidden")
        fake_keyring.fail_get = True
        assert key_store.load_key() == "gsk_hidden"

    def test_read_failure_with_keyring_only_store_is_empty(self, fake_keyring):
        key_store.save_key("gsk_ok")
        fake_keyring.fail_get = True
        assert key_store.load_key() == ""
