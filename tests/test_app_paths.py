"""Tests for writable app-data paths and legacy data migration."""
from __future__ import annotations

from pathlib import Path

import pytest

from utils import app_paths, key_store


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(app_paths.ENV_DATA_DIR, raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


class TestPathResolution:
    def test_source_run_uses_repository_layout(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr(app_paths, "install_root", lambda: repo)
        monkeypatch.setattr(app_paths, "is_frozen", lambda: False)

        assert app_paths.data_dir() == repo
        assert app_paths.settings_path() == repo / "config" / "settings.toml"
        assert app_paths.log_path() == repo / "ghostmind.log"
        assert app_paths.update_state_path() == repo / "config" / "update_state.json"

    def test_frozen_build_uses_localappdata(self, tmp_path, monkeypatch):
        local = tmp_path / "Local"
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setattr(app_paths, "is_frozen", lambda: True)

        data = local / "GhostMind" / "data"
        assert app_paths.data_dir() == data
        assert app_paths.settings_path() == data / "settings.toml"
        assert app_paths.log_path() == data / "ghostmind.log"
        assert app_paths.update_state_path() == data / "update_state.json"

    def test_override_wins_and_uses_flat_layout(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom-data"
        monkeypatch.setenv(app_paths.ENV_DATA_DIR, str(custom))
        monkeypatch.setattr(app_paths, "install_root", lambda: _repo(tmp_path))
        monkeypatch.setattr(app_paths, "is_frozen", lambda: False)

        assert app_paths.data_dir() == custom
        assert app_paths.settings_path() == custom / "settings.toml"
        assert app_paths.log_path() == custom / "ghostmind.log"
        assert app_paths.update_state_path() == custom / "update_state.json"

    def test_key_store_fallback_uses_active_settings_path(self, tmp_path, monkeypatch):
        expected = tmp_path / "data" / "settings.toml"
        monkeypatch.setattr(app_paths, "settings_path", lambda: expected)
        assert key_store._fallback_path() == expected


class TestMigration:
    def _legacy(self, tmp_path: Path) -> Path:
        legacy = tmp_path / "legacy"
        config = legacy / "config"
        config.mkdir(parents=True)
        (config / "settings.toml").write_text('[api]\nmodel = "m"\n', encoding="utf-8")
        (config / "update_state.json").write_text('{"popup_count": 2}', encoding="utf-8")
        (config / "anonymous_id.txt").write_text("install-id", encoding="utf-8")
        (legacy / "ghostmind.log").write_text("current log", encoding="utf-8")
        (legacy / "ghostmind.log.1").write_text("old log", encoding="utf-8")
        return legacy

    def test_copies_all_legacy_data_to_flat_data_dir(self, tmp_path):
        legacy = self._legacy(tmp_path)
        data = tmp_path / "data"

        copied = app_paths.migrate_legacy_data(legacy, data)

        assert len(copied) == 5
        assert (data / "settings.toml").read_text(encoding="utf-8") == (
            '[api]\nmodel = "m"\n'
        )
        assert (data / "update_state.json").read_text(encoding="utf-8") == (
            '{"popup_count": 2}'
        )
        assert (data / "config" / "anonymous_id.txt").read_text(encoding="utf-8") == (
            "install-id"
        )
        assert (data / "ghostmind.log").read_text(encoding="utf-8") == "current log"
        assert (data / "ghostmind.log.1").read_text(encoding="utf-8") == "old log"

    def test_never_overwrites_existing_data(self, tmp_path):
        legacy = self._legacy(tmp_path)
        data = tmp_path / "data"
        data.mkdir()
        (data / "settings.toml").write_text("new settings", encoding="utf-8")
        (data / "ghostmind.log").write_text("new log", encoding="utf-8")

        copied = app_paths.migrate_legacy_data(legacy, data)

        assert (data / "settings.toml").read_text(encoding="utf-8") == "new settings"
        assert (data / "ghostmind.log").read_text(encoding="utf-8") == "new log"
        assert data / "update_state.json" in copied
        assert data / "settings.toml" not in copied
        assert data / "ghostmind.log" not in copied

    def test_same_root_is_a_noop(self, tmp_path):
        legacy = self._legacy(tmp_path)
        copied = app_paths.migrate_legacy_data(legacy, legacy)
        assert copied == []
        assert not (legacy / "settings.toml").exists()

    def test_missing_legacy_data_is_a_noop(self, tmp_path):
        copied = app_paths.migrate_legacy_data(tmp_path / "missing", tmp_path / "data")
        assert copied == []

    def test_key_store_reads_migrated_plaintext_fallback(self, tmp_path, monkeypatch):
        legacy = tmp_path / "legacy"
        config = legacy / "config"
        config.mkdir(parents=True)
        (config / "settings.toml").write_text(
            '[key_storage]\napi_key = "gsk_migrated"\n', encoding="utf-8"
        )
        data = tmp_path / "data"
        app_paths.migrate_legacy_data(legacy, data)

        monkeypatch.setenv(app_paths.ENV_DATA_DIR, str(data))
        monkeypatch.setattr(key_store, "_KEYRING", False, raising=False)
        assert key_store.load_key() == "gsk_migrated"
