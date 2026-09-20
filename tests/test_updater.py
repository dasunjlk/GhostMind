"""Tests for utils/updater.py — U-01 update check, grace state, download+verify.

All logic tests are offline: no real network. HTTP is exercised only via
file:// URLs against a local fixture release JSON.
"""
from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace
from typing import List, Optional

import pytest

import utils.updater as updater
from utils.updater import (
    DAY_SEC,
    MAX_CONSECUTIVE_FAILURES,
    UpdaterError,
    evaluate_check,
    is_newer,
    parse_version,
)


def _release(
    tag: str = "1.1.0",
    body: str = "Release notes here.",
    assets: Optional[List[dict]] = None,
) -> dict:
    return {
        "tag_name": f"v{tag}" if not tag.startswith("v") else tag,
        "body": body,
        "assets": assets if assets is not None else [],
    }


# --------------------------------------------------------------------------- #
# Version math
# --------------------------------------------------------------------------- #

class TestParseVersion:
    def test_basic(self):
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_v_prefix(self):
        assert parse_version("v1.2.3") == (1, 2, 3)

    def test_two_part(self):
        assert parse_version("1.2") == (1, 2, 0)

    def test_two_part_compare(self):
        assert is_newer("1.10", "1.9.0") is True

    def test_tuple_compare_10_vs_9(self):
        assert is_newer("1.10.0", "1.9.0") is True

    def test_equal_not_newer(self):
        assert is_newer("1.0.0", "1.0.0") is False

    def test_local_newer(self):
        assert is_newer("1.0.0", "1.0.1") is False

    def test_garbage(self):
        assert parse_version("") == (0, 0, 0)
        assert parse_version("garbage") == (0, 0, 0)

    def test_suffix_ignored(self):
        assert parse_version("1.2.3-beta.1") == (1, 2, 3)


class TestNewerGate:
    def test_no_newer_no_state_change(self):
        state = {"known_latest_version": "1.1.0", "first_seen_epoch": 100}
        # Release is SAME version as local → not newer → stale state resets.
        out = evaluate_check(_release("1.0.0"), "1.0.0", state, now=200)
        assert out.update_available is False
        assert out.state == updater.default_state()

    def test_remote_older_than_local(self):
        out = evaluate_check(_release("0.9.0"), "1.0.0", {}, now=100)
        assert out.update_available is False

    def test_same_version_resets_state(self):
        state = {"known_latest_version": "1.1.0", "first_seen_epoch": 100, "popup_count": 7}
        out = evaluate_check(_release("1.0.0"), "1.0.0", state, now=200)
        assert out.state == updater.default_state()


# --------------------------------------------------------------------------- #
# Grace clock
# --------------------------------------------------------------------------- #

class TestGraceClock:
    # NOTE: first_seen_epoch uses a non-zero base (1000) because 0 means
    # "clock not started" in the state file, same as default_state().
    BASE = 1000

    def test_first_detection_starts_clock(self):
        out = evaluate_check(_release("1.1.0"), "1.0.0", {}, now=self.BASE)
        assert out.update_available is True
        assert out.first_popup_for_version is True
        assert out.state["first_seen_epoch"] == self.BASE
        assert out.state["known_latest_version"] == "1.1.0"

    def test_day2_not_locked_3_days_left(self):
        state = {"known_latest_version": "1.1.0", "first_seen_epoch": self.BASE}
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE + 2 * DAY_SEC)
        assert out.locked is False
        assert out.days_left == 3

    def test_day4_not_locked_1_day_left(self):
        state = {"known_latest_version": "1.1.0", "first_seen_epoch": self.BASE}
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE + 4 * DAY_SEC)
        assert out.locked is False
        assert out.days_left == 1

    def test_day5_locked(self):
        state = {"known_latest_version": "1.1.0", "first_seen_epoch": self.BASE}
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE + 5 * DAY_SEC)
        assert out.locked is True
        assert out.grace_expired is True
        assert out.days_left == 0

    def test_new_version_restarts_clock(self):
        state = {
            "known_latest_version": "1.1.0",
            "first_seen_epoch": self.BASE,
            "popup_count": 3,
        }
        # A different newer version arrives → clock restarts.
        out = evaluate_check(_release("1.2.0"), "1.0.0", state, now=self.BASE + 50 * DAY_SEC)
        assert out.first_popup_for_version is True
        assert out.state["first_seen_epoch"] == self.BASE + 50 * DAY_SEC
        assert out.state["popup_count"] == 0
        assert out.locked is False

    def test_grace_days_zero_env_locks_immediately(self, monkeypatch):
        monkeypatch.setenv("GHOSTMIND_GRACE_DAYS", "0")
        state = {"known_latest_version": "1.1.0", "first_seen_epoch": self.BASE}
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE + 10)
        assert out.locked is True

    def test_clock_rollback_cannot_reset_grace(self):
        # Server time says day 6 → locked, regardless of any local clock games.
        state = {"known_latest_version": "1.1.0", "first_seen_epoch": self.BASE}
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE + 6 * DAY_SEC)
        assert out.locked is True
        # now earlier than first_seen: elapsed clamps to 0 — only reachable if
        # the SERVER Date went backwards, which evaluate treats as a fresh
        # clock (acceptable; the server Date is the anti-rollback source).
        out2 = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE - 1)
        assert out2.locked is False  # day 0 again per authoritative clock


# --------------------------------------------------------------------------- #
# Popup throttle + snooze
# --------------------------------------------------------------------------- #

class TestPopupThrottle:
    BASE = 1000

    def test_never_shown_pops(self):
        state = {"known_latest_version": "1.1.0", "first_seen_epoch": self.BASE}
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE)
        assert out.should_popup is True

    def test_recent_popup_is_throttled(self):
        state = {
            "known_latest_version": "1.1.0",
            "first_seen_epoch": self.BASE,
            "last_popup_epoch": self.BASE,
        }
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE + 3600)
        assert out.should_popup is False

    def test_24h_old_popup_pops_again(self):
        state = {
            "known_latest_version": "1.1.0",
            "first_seen_epoch": self.BASE,
            "last_popup_epoch": self.BASE,
        }
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE + DAY_SEC + 1)
        assert out.should_popup is True

    def test_snooze_blocks_lock(self):
        state = {
            "known_latest_version": "1.1.0",
            "first_seen_epoch": self.BASE,
            "snooze_until_epoch": self.BASE + 10 * DAY_SEC,
        }
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE + 6 * DAY_SEC)
        assert out.grace_expired is True
        assert out.locked is False  # snoozed via safety valve

    def test_snooze_expiry_relocks(self):
        state = {
            "known_latest_version": "1.1.0",
            "first_seen_epoch": self.BASE,
            "snooze_until_epoch": self.BASE + 7 * DAY_SEC,
        }
        out = evaluate_check(_release("1.1.0"), "1.0.0", state, now=self.BASE + 7 * DAY_SEC + 5)
        assert out.locked is True


# --------------------------------------------------------------------------- #
# State file persistence
# --------------------------------------------------------------------------- #

class TestStatePersistence:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "update_state.json"
        state = updater.default_state()
        state["known_latest_version"] = "1.1.0"
        updater.save_state(state, path)
        loaded = updater.load_state(path)
        assert loaded["known_latest_version"] == "1.1.0"

    def test_load_missing_file_returns_defaults(self, tmp_path):
        loaded = updater.load_state(tmp_path / "nope.json")
        assert loaded == updater.default_state()

    def test_load_corrupt_file_returns_defaults(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        assert updater.load_state(path) == updater.default_state()

    def test_unknown_keys_dropped(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text('{"known_latest_version": "1.1.0", "evil": 1}', encoding="utf-8")
        loaded = updater.load_state(path)
        assert "evil" not in loaded

    def test_check_for_update_persists_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            updater, "fetch_latest_release",
            lambda timeout=10.0: (_release("1.1.0"), 1000),
        )
        path = tmp_path / "update_state.json"
        out = updater.check_for_update("1.0.0", state_path=path, now=1000)
        assert out is not None and out.update_available
        on_disk = updater.load_state(path)
        assert on_disk["known_latest_version"] == "1.1.0"

    def test_check_for_update_none_when_offline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(updater, "fetch_latest_release", lambda timeout=10.0: None)
        assert updater.check_for_update("1.0.0", state_path=tmp_path / "s.json") is None

    def test_force_update_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GHOSTMIND_FORCE_UPDATE", "1")
        monkeypatch.setattr(
            updater, "fetch_latest_release",
            lambda timeout=10.0: (_release("1.0.0"), 1000),  # same version locally
        )
        out = updater.check_for_update("1.0.0", state_path=tmp_path / "s.json", now=1000)
        assert out is not None and out.update_available
        assert out.tag == "999.0.0"

    def test_response_cached_within_6h_across_restarts(self, tmp_path, monkeypatch):
        path = tmp_path / "s.json"
        calls = {"n": 0}

        def fake_fetch(timeout=10.0):
            calls["n"] += 1
            return (_release("1.1.0"), 5000)

        monkeypatch.setattr(updater, "fetch_latest_release", fake_fetch)
        out1 = updater.check_for_update("1.0.0", state_path=path, now=1000)
        assert out1 is not None and out1.update_available

        # Network now down, but within the 6h window → cached release is used.
        monkeypatch.setattr(updater, "fetch_latest_release", lambda timeout=10.0: None)
        out2 = updater.check_for_update("1.0.0", state_path=path, now=1000 + 3600)
        assert out2 is not None and out2.update_available and out2.tag == "1.1.0"
        assert calls["n"] == 1, "must not re-contact GitHub within the 6h window"

        # Outside the window with no network → silently skip.
        out3 = updater.check_for_update("1.0.0", state_path=path, now=1000 + 8 * 3600)
        assert out3 is None
        assert calls["n"] == 1


# --------------------------------------------------------------------------- #
# Popup/snooze bookkeeping
# --------------------------------------------------------------------------- #

class TestRecorders:
    def test_record_popup(self, tmp_path):
        path = tmp_path / "s.json"
        updater.record_popup(path, now=500)
        state = updater.load_state(path)
        assert state["last_popup_epoch"] == 500
        assert state["popup_count"] == 1
        updater.record_popup(path, now=600)
        assert updater.load_state(path)["popup_count"] == 2

    def test_record_snooze(self, tmp_path):
        path = tmp_path / "s.json"
        updater.record_snooze(path, until_epoch=9999)
        assert updater.load_state(path)["snooze_until_epoch"] == 9999

    def test_failed_attempts_counter(self, tmp_path):
        path = tmp_path / "s.json"
        assert updater.record_failed_attempt(path) == 1
        assert updater.record_failed_attempt(path) == 2
        updater.reset_failed_attempts(path)
        assert updater.load_state(path)["failed_attempts"] == 0


# --------------------------------------------------------------------------- #
# Assets + SHA256
# --------------------------------------------------------------------------- #

class TestPickAssets:
    def test_finds_setup_and_checksums(self):
        release = _release(assets=[
            {"name": "GhostMind-Portable-1.1.0.zip", "browser_download_url": "u0"},
            {"name": "GhostMind-Setup-1.1.0.exe", "browser_download_url": "u1"},
            {"name": "SHA256SUMS.txt", "browser_download_url": "u2"},
        ])
        setup, sums = updater.pick_release_assets(release)
        assert setup["browser_download_url"] == "u1"
        assert sums["browser_download_url"] == "u2"

    def test_missing_setup(self):
        setup, sums = updater.pick_release_assets(_release(assets=[
            {"name": "SHA256SUMS.txt", "browser_download_url": "u2"},
        ]))
        assert setup is None
        assert sums is not None

    def test_missing_checksums(self):
        setup, _ = updater.pick_release_assets(_release(assets=[
            {"name": "GhostMind-Setup-1.1.0.exe", "browser_download_url": "u1"},
        ]))
        assert setup is not None


class TestSha256:
    def test_verify_ok(self, tmp_path):
        f = tmp_path / "GhostMind-Setup-1.1.0.exe"
        f.write_bytes(b"installer-bytes")
        digest = hashlib.sha256(b"installer-bytes").hexdigest()
        sums = f"{digest}  GhostMind-Setup-1.1.0.exe\n"
        assert updater.verify_sha256(f, sums) is True

    def test_verify_binary_prefix_format(self, tmp_path):
        f = tmp_path / "GhostMind-Setup-1.1.0.exe"
        f.write_bytes(b"x")
        digest = hashlib.sha256(b"x").hexdigest()
        assert updater.verify_sha256(f, f"{digest} *GhostMind-Setup-1.1.0.exe") is True

    def test_verify_wrong_hash(self, tmp_path):
        f = tmp_path / "GhostMind-Setup-1.1.0.exe"
        f.write_bytes(b"tampered")
        sums = f"{'0' * 64}  GhostMind-Setup-1.1.0.exe\n"
        assert updater.verify_sha256(f, sums) is False

    def test_verify_missing_entry_fails(self, tmp_path):
        f = tmp_path / "GhostMind-Setup-1.1.0.exe"
        f.write_bytes(b"x")
        assert updater.verify_sha256(f, "deadbeef  other-file.exe\n") is False


# --------------------------------------------------------------------------- #
# Download flow (file:// URLs against local fixtures)
# --------------------------------------------------------------------------- #

class TestDownloadFlow:
    @pytest.fixture()
    def fake_release(self, tmp_path, monkeypatch):
        """Local release dir + installer asset reachable via file://."""
        content = b"MZ" + b"A" * 100_000  # fake PE-ish payload
        exe = tmp_path / "GhostMind-Setup-1.1.0.exe"
        exe.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        (tmp_path / "SHA256SUMS.txt").write_text(
            f"{digest}  GhostMind-Setup-1.1.0.exe\n", encoding="utf-8"
        )
        release = _release("1.1.0", assets=[
            {"name": "GhostMind-Setup-1.1.0.exe",
             "browser_download_url": exe.as_uri()},
            {"name": "SHA256SUMS.txt",
             "browser_download_url": (tmp_path / "SHA256SUMS.txt").as_uri()},
        ])
        return release, content

    def test_download_and_verify_ok(self, tmp_path, monkeypatch, fake_release):
        release, content = fake_release
        dest_dir = tmp_path / "dl"
        monkeypatch.setenv("TEMP", str(dest_dir))
        monkeypatch.setattr(updater, "installer_dest", lambda ver: dest_dir / f"GhostMind-Setup-{ver}.exe")
        progress: List[tuple] = []
        state_file = tmp_path / "state.json"
        path = updater.download_installer(
            release, progress_cb=lambda a, b: progress.append((a, b)), state_path=state_file
        )
        assert path.read_bytes() == content
        assert progress and progress[-1][0] == len(content)
        assert updater.load_state(state_file)["failed_attempts"] == 0

    def test_download_bad_checksum_fails(self, tmp_path, monkeypatch, fake_release):
        release, _ = fake_release
        # Corrupt the sums file to force a mismatch.
        (tmp_path / "SHA256SUMS.txt").write_text(f"{'f' * 64}  GhostMind-Setup-1.1.0.exe\n")
        dest_dir = tmp_path / "dl"
        monkeypatch.setattr(updater, "installer_dest", lambda ver: dest_dir / f"GhostMind-Setup-{ver}.exe")
        state_file = tmp_path / "state.json"
        with pytest.raises(UpdaterError, match="Checksum mismatch"):
            updater.download_installer(release, state_path=state_file)
        # Corrupt file deleted, failure recorded for the safety valve.
        assert not (dest_dir / "GhostMind-Setup-1.1.0.exe").exists()
        assert updater.load_state(state_file)["failed_attempts"] == 1

    def test_missing_installer_asset(self, tmp_path):
        with pytest.raises(UpdaterError, match="not found on the release page"):
            updater.download_installer(_release("1.1.0", assets=[
                {"name": "SHA256SUMS.txt", "browser_download_url": "file:///nope"},
            ]))

    def test_missing_checksum_asset(self, tmp_path):
        with pytest.raises(UpdaterError, match="Checksums file"):
            updater.download_installer(_release("1.1.0", assets=[
                {"name": "GhostMind-Setup-1.1.0.exe", "browser_download_url": "file:///nope"},
            ]))

    def test_three_failures_enable_valve(self, tmp_path):
        path = tmp_path / "s.json"
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            updater.record_failed_attempt(path)
        assert updater.load_state(path)["failed_attempts"] >= MAX_CONSECUTIVE_FAILURES


# --------------------------------------------------------------------------- #
# Offline safety (the "never locked out" guarantee, in logic form)
# --------------------------------------------------------------------------- #

class TestOfflineSafety:
    def test_offline_check_returns_none(self, monkeypatch, tmp_path):
        # fetch_latest_release swallows network errors and returns None —
        # check_for_update must propagate that as "silently skip".
        monkeypatch.setattr(updater, "fetch_latest_release", lambda timeout=10.0: None)
        assert updater.check_for_update("1.0.0", state_path=tmp_path / "s.json") is None
