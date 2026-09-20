"""Tests for ui/update_popup.py — close blocking, snooze, safety valve.

Uses a real QApplication (no exec), spies on the state recorders, no network.
"""
from __future__ import annotations

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
