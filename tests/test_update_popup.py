"""Tests for ui/update_popup.py — close blocking, snooze, safety valve.

Uses a real QApplication (no exec), spies on the state recorders, no network.
"""
from __future__ import annotations

import json
from typing import List

import pytest
from PyQt6.QtWidgets import QApplication, QDialog

import utils.updater as updater
from ui.update_popup import UpdatePopup
from utils.updater import UpdateCheck


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def spies(monkeypatch, tmp_path):
    """Capture recorder calls and route state at a temp file."""
    calls: List[str] = []

    def _rec_popup(path=None, now=None):
        calls.append("popup")

    def _rec_snooze(path=None, until_epoch=None):
        calls.append(f"snooze:{until_epoch}")

    def _reset(path=None):
        calls.append("reset_attempts")

    monkeypatch.setattr(updater, "record_popup", _rec_popup)
    monkeypatch.setattr(updater, "record_snooze", _rec_snooze)
    monkeypatch.setattr(updater, "reset_failed_attempts", _reset)
    return calls


def _check(locked: bool) -> UpdateCheck:
    return UpdateCheck(
        tag="1.1.0",
        notes="Test notes",
        assets=[],
        update_available=True,
        locked=locked,
        days_left=0 if locked else 4,
    )


class TestGracePhase:
    def test_close_button_is_closable(self, qapp):
        popup = UpdatePopup(_check(locked=False), locked=False)
        assert popup._update_btn.text() == "Update Now"
        popup.show()
        assert popup.isVisible()
        popup.close()
        assert not popup.isVisible()

    def test_later_records_popup_and_snooze(self, qapp, spies):
        popup = UpdatePopup(_check(locked=False), locked=False)
        popup.reject()  # what Esc / X / Later all route through
        assert "popup" in spies
        assert any(s.startswith("snooze:") for s in spies)
        assert popup.result() == QDialog.DialogCode.Rejected.value

    def test_has_later_button(self, qapp):
        popup = UpdatePopup(_check(locked=False), locked=False)
        later = [b for b in popup.findChildren(type(popup._update_btn))
                 if b.text() == "Later"]
        assert later, "grace dialog must offer a Later button"


class TestLockedPhase:
    def test_esc_and_close_blocked(self, qapp, spies):
        popup = UpdatePopup(_check(locked=True), locked=True)
        popup.show()
        popup.reject()          # Esc key — overridden to be a no-op when locked
        popup.close()           # X / Alt+F4 — closeEvent ignored when locked
        assert spies == [], "locked dialog must not record a snooze on close"
        assert popup.isVisible(), "locked dialog must stay open"

    def test_no_later_button(self, qapp):
        popup = UpdatePopup(_check(locked=True), locked=True)
        later = [b for b in popup.findChildren(type(popup._update_btn))
                 if b.text() == "Later"]
        assert not later, "locked dialog must not offer Later"

    def test_window_flags_block_system_close(self, qapp):
        popup = UpdatePopup(_check(locked=True), locked=True)
        assert bool(popup.windowFlags() & __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.WindowType.CustomizeWindowHint)
        assert popup.windowModality() == __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.WindowModality.ApplicationModal


class TestSafetyValve:
    def test_valve_hidden_below_threshold(self, qapp, tmp_path):
        popup = UpdatePopup(_check(locked=True), locked=True, state_path=tmp_path / "s.json")
        assert popup._valve_btn.isHidden()

    def test_valve_unlocks_for_24h(self, qapp, spies, tmp_path):
        import time

        popup = UpdatePopup(_check(locked=True), locked=True, state_path=tmp_path / "s.json")
        popup._valve_btn.setVisible(True)
        before = int(time.time())
        popup._on_safety_valve()
        snoozed = [s for s in spies if s.startswith("snooze:")]
        assert snoozed, "valve must snooze"
        until = int(snoozed[0].split(":")[1])
        assert until - before >= 23 * 3600  # ~24h unlock
        assert "reset_attempts" in spies
        assert popup.result() == QDialog.DialogCode.Accepted.value


class TestInstallerLaunch:
    def test_startfile_quits_app(self, qapp, monkeypatch, tmp_path):
        """U-01 3.7: the installer needs GhostMind to exit before replacing files."""
        import ui.update_popup as popup_mod

        launched: List[str] = []
        monkeypatch.setattr(
            popup_mod.os, "startfile", lambda path: launched.append(path), raising=False
        )

        quit_calls: List[bool] = []

        class FakeApp:
            def quit(self):
                quit_calls.append(True)

        fake_qapp = type(
            "FakeQApplication",
            (),
            {"instance": staticmethod(lambda: FakeApp())},
        )
        monkeypatch.setattr(popup_mod, "QApplication", fake_qapp)

        popup = UpdatePopup(_check(locked=True), locked=True, state_path=tmp_path / "s.json")
        popup._installer_path = str(tmp_path / "GhostMind-Setup-1.1.0.exe")
        popup._run_installer()

        assert launched == [popup._installer_path]
        assert quit_calls == [True], "app must quit so Inno Setup can replace files"


class TestGraceBannerSuppression:
    """C6: a grace-phase check must show the in-app banner, never the popup."""

    @pytest.fixture
    def controller(self, qapp, monkeypatch):
        import main as app_main

        monkeypatch.setattr(app_main, "resolve_api_key", lambda **kwargs: "")
        monkeypatch.setattr(
            app_main.GhostMindController, "_register_hotkeys", lambda self: None
        )
        ctrl = app_main.GhostMindController(qapp, dict(app_main.DEFAULT_SETTINGS))
        ctrl._update_timer.stop()
        yield ctrl
        ctrl._update_timer.stop()
        if ctrl._update_popup is not None:
            ctrl._update_popup.close()
            ctrl._update_popup.deleteLater()
        ctrl.hotkeys.unregister_all()
        ctrl.overlay.close_event_allowed = True
        ctrl.overlay.close()
        ctrl._tray.hide()
        ctrl.deleteLater()
        qapp.processEvents()

    def test_grace_check_does_not_open_popup(self, controller):
        controller.overlay.show()
        check = UpdateCheck(
            tag="1.1.0",
            notes="Test notes",
            assets=[],
            update_available=True,
            locked=False,
            should_popup=True,
        )
        controller._on_update_check_done(check)
        assert controller._update_popup is None
        assert controller.overlay._update_banner.isVisible()


class TestPreDownloadedInstaller:
    """C7: the popup skips downloading when the version is already fetched,
    SHA-256 verified, and still on disk."""

    def _seed(self, tmp_path, tag: str = "1.1.0", with_file: bool = True):
        exe = tmp_path / f"GhostMind-Setup-{tag}.exe"
        if with_file:
            exe.write_bytes(b"MZ" + b"A" * 1000)
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "downloaded_version": tag,
                    "downloaded_path": str(exe),
                    "downloaded_sha_ok": True,
                }
            ),
            encoding="utf-8",
        )
        return exe, state_file

    def test_popup_reuses_pre_downloaded_installer(self, qapp, spies, tmp_path):
        exe, state_file = self._seed(tmp_path)
        popup = UpdatePopup(_check(locked=False), locked=False, state_path=state_file)
        assert popup._installer_path == str(exe)
        assert popup._update_btn.text() == "Restart installer"
        assert "already downloaded" in popup._status.text()

    def test_clicking_pre_downloaded_runs_installer(
        self, qapp, spies, tmp_path, monkeypatch
    ):
        import ui.update_popup as popup_mod

        exe, state_file = self._seed(tmp_path)
        launched: List[str] = []
        monkeypatch.setattr(
            popup_mod.os, "startfile", lambda p: launched.append(str(p)), raising=False
        )
        quit_calls: List[bool] = []

        class FakeApp:
            def quit(self):
                quit_calls.append(True)

        fake_qapp = type(
            "FakeQApplication",
            (),
            {"instance": staticmethod(lambda: FakeApp())},
        )
        monkeypatch.setattr(popup_mod, "QApplication", fake_qapp)

        popup = UpdatePopup(_check(locked=False), locked=False, state_path=state_file)
        popup._update_btn.click()
        assert launched == [str(exe)]
        assert quit_calls == [True]
        assert "popup" in spies, "installer launch must record the popup"

    def test_missing_pre_download_falls_back_to_normal_flow(self, qapp, spies, tmp_path):
        _exe, state_file = self._seed(tmp_path, with_file=False)
        popup = UpdatePopup(_check(locked=False), locked=False, state_path=state_file)
        assert popup._update_btn.text() == "Update Now"
        assert popup._installer_path is None

    def test_pre_download_for_other_version_ignored(self, qapp, spies, tmp_path):
        _exe, state_file = self._seed(tmp_path, tag="9.9.9")
        popup = UpdatePopup(_check(locked=False), locked=False, state_path=state_file)
        assert popup._update_btn.text() == "Update Now"
        assert popup._installer_path is None
