"""Tests for the in-app feedback channel (C13).

All offline: sentry_sdk.capture_event is monkeypatched (no real network),
and the channel is activated via GHOSTMIND_FORCE_TELEMETRY=1 where needed
because error reporting auto-disables under pytest.
"""
from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QApplication

import main as app_main
from ui.feedback_panel import FeedbackPanel
from ui.settings_panel import SettingsPanel
from utils import error_reporter, feedback
from version import __version__


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def channel_on(monkeypatch):
    """Activate the feedback channel despite the pytest auto-disable."""
    monkeypatch.setenv("GHOSTMIND_FORCE_TELEMETRY", "1")
    monkeypatch.delenv("GHOSTMIND_NO_TELEMETRY", raising=False)


@pytest.fixture
def captures(monkeypatch):
    """Record capture_event calls; each returns a fake event id."""
    events: list[dict] = []
    import sentry_sdk

    monkeypatch.setattr(sentry_sdk, "capture_event", lambda event: (events.append(event), "event-id-1")[1])
    return events


class TestPayload:
    def test_payload_shape(self):
        payload = feedback.build_payload("bug", 4, "Scan missed text", "me@x.com")
        assert set(payload) == {"type", "rating", "text", "contact", "version", "os", "install_id"}
        assert payload["type"] == "bug"
        assert payload["rating"] == 4
        assert payload["text"] == "Scan missed text"
        assert payload["contact"] == "me@x.com"
        assert payload["version"] == __version__
        assert payload["os"]
        assert len(payload["install_id"]) == 8

    def test_unknown_type_falls_back_to_other(self):
        assert feedback.build_payload("nonsense", None, "", "")["type"] == "other"

    def test_rating_out_of_range_becomes_none(self):
        assert feedback.build_payload("bug", 0, "", "")["rating"] is None
        assert feedback.build_payload("bug", 99, "", "")["rating"] is None

    def test_rating_string_is_accepted(self):
        assert feedback.build_payload("bug", "3", "", "")["rating"] == 3

    def test_text_and_contact_are_scrubbed(self):
        payload = feedback.build_payload(
            "bug", None,
            "key is gsk_ABCDEF0123456789abcdef0123456789 here",
            "api_key = supersecretvalue",
        )
        assert "gsk_ABCDEF" not in payload["text"]
        assert "supersecretvalue" not in payload["contact"]


class TestChannelState:
    def test_active_when_forced(self, channel_on):
        assert error_reporter.feedback_channel_state() == (True, "")

    def test_disabled_reason_is_user_facing(self, monkeypatch):
        monkeypatch.setenv("GHOSTMIND_NO_TELEMETRY", "1")
        monkeypatch.delenv("GHOSTMIND_FORCE_TELEMETRY", raising=False)
        active, reason = error_reporter.feedback_channel_state()
        assert active is False
        assert "GHOSTMIND_NO_TELEMETRY" in reason


class TestSubmit:
    def test_submit_success_sends_feedback_event(self, channel_on, captures):
        payload = feedback.build_payload("suggestion", 5, "Add dark red theme", "")
        ok, msg = feedback.submit_feedback(payload)

        assert (ok, msg) == (True, "")
        assert len(captures) == 1
        event = captures[0]
        assert event["type"] == "feedback"
        assert event["contexts"]["feedback"]["message"] == "Add dark red theme"
        assert event["contexts"]["feedback"]["name"] == "GhostMind user"
        assert event["tags"]["feedback_type"] == "suggestion"
        assert event["extra"]["rating"] == 5

    def test_submit_links_install_id(self, channel_on, captures):
        payload = feedback.build_payload("bug", None, "boom", "")
        feedback.submit_feedback(payload)

        sent_user_id = captures[0]["user"]["id"]
        assert sent_user_id == payload["install_id"]

    def test_opt_out_neither_sends_nor_stores(self, monkeypatch, captures, tmp_path):
        monkeypatch.setenv("GHOSTMIND_NO_TELEMETRY", "1")
        monkeypatch.delenv("GHOSTMIND_FORCE_TELEMETRY", raising=False)
        payload = feedback.build_payload("bug", None, "boom", "")

        ok, msg = feedback.submit_feedback(payload, data_dir=tmp_path)

        assert ok is False
        assert "GHOSTMIND_NO_TELEMETRY" in msg
        assert "github.com/dasunjlk/GhostMind/issues" in msg
        assert captures == [], "disabled channel must not send"
        assert not (tmp_path / "config" / "feedback_outbox.jsonl").exists()

    def test_send_failure_parks_payload_in_outbox(self, channel_on, monkeypatch, tmp_path):
        import sentry_sdk

        def _boom(event):
            raise ConnectionError("offline")

        monkeypatch.setattr(sentry_sdk, "capture_event", _boom)
        payload = feedback.build_payload("bug", 2, "crashed", "")

        ok, msg = feedback.submit_feedback(payload, data_dir=tmp_path)

        assert ok is False
        assert "next time you're online" in msg
        lines = (tmp_path / "config" / "feedback_outbox.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["text"] == "crashed"

    def test_dropped_event_parks_payload_in_outbox(self, channel_on, monkeypatch, tmp_path):
        import sentry_sdk

        monkeypatch.setattr(sentry_sdk, "capture_event", lambda event: None)
        payload = feedback.build_payload("other", None, "hm", "")

        ok, _msg = feedback.submit_feedback(payload, data_dir=tmp_path)

        assert ok is False
        assert len(feedback.load_outbox(tmp_path)) == 1


class TestOutbox:
    def test_flush_sends_everything_and_clears(self, channel_on, captures, tmp_path):
        feedback._append_outbox(feedback.build_payload("bug", None, "one", ""), tmp_path)
        feedback._append_outbox(feedback.build_payload("bug", None, "two", ""), tmp_path)

        sent = feedback.flush_outbox(tmp_path)

        assert sent == 2
        assert captures[0]["contexts"]["feedback"]["message"] == "one"
        assert captures[1]["contexts"]["feedback"]["message"] == "two"
        assert not (tmp_path / "config" / "feedback_outbox.jsonl").exists()

    def test_flush_keeps_unsent(self, channel_on, monkeypatch, tmp_path):
        import sentry_sdk

        feedback._append_outbox(feedback.build_payload("bug", None, "stay", ""), tmp_path)
        monkeypatch.setattr(sentry_sdk, "capture_event", lambda event: None)

        sent = feedback.flush_outbox(tmp_path)

        assert sent == 0
        assert [p["text"] for p in feedback.load_outbox(tmp_path)] == ["stay"]

    def test_flush_disabled_is_a_noop(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GHOSTMIND_NO_TELEMETRY", "1")
        monkeypatch.delenv("GHOSTMIND_FORCE_TELEMETRY", raising=False)
        feedback._append_outbox(feedback.build_payload("bug", None, "stay", ""), tmp_path)

        assert feedback.flush_outbox(tmp_path) == 0
        assert len(feedback.load_outbox(tmp_path)) == 1


class _ImmediateThread:
    """Runs its target synchronously (test stand-in for threading.Thread)."""

    def __init__(self, target=None, daemon=None, *args, **kwargs):
        self._target = target

    def start(self):
        if self._target is not None:
            self._target()

    def isRunning(self):
        return False


class TestFeedbackPanel:
    def test_initial_state(self, qapp):
        panel = FeedbackPanel()
        assert panel._selected_type() == "works_great"
        assert panel._selected_rating() is None
        assert panel._send_btn.isEnabled()

    def test_type_and_rating_selection(self, qapp):
        panel = FeedbackPanel()
        bug_btn = next(
            b for b in panel._type_group.buttons()
            if b.property("feedbackType") == "bug"
        )
        bug_btn.click()
        assert panel._selected_type() == "bug"

        faces = panel._rating_buttons
        faces[3].click()  # 🙁
        assert panel._selected_rating() == 4
        faces[1].click()  # 🙂 replaces 🙁 (one rating at a time)
        assert panel._selected_rating() == 2
        faces[1].click()  # clicking the selected face clears it
        assert panel._selected_rating() is None

    def test_send_flow_success(self, qapp, monkeypatch):
        import ui.feedback_panel as panel_mod

        calls: list[dict] = []
        monkeypatch.setattr(
            panel_mod.threading, "Thread", _ImmediateThread
        )
        monkeypatch.setattr(
            panel_mod.feedback,
            "submit_feedback",
            lambda payload, data_dir=None: calls.append(payload) or (True, ""),
        )
        panel = FeedbackPanel()
        panel._text.setPlainText("Great app!")
        panel._send_btn.click()

        assert len(calls) == 1
        assert calls[0]["text"] == "Great app!"
        assert calls[0]["type"] == "works_great"
        assert "✓ Sent — thank you!" in panel._status.text()
        assert panel._text.toPlainText() == "", "fields reset after success"

    def test_send_failure_shows_saved_note(self, qapp, monkeypatch):
        import ui.feedback_panel as panel_mod

        monkeypatch.setattr(panel_mod.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(
            panel_mod.feedback,
            "submit_feedback",
            lambda payload, data_dir=None: (False, "Saved — we'll send it next time you're online."),
        )
        panel = FeedbackPanel()
        panel._send_btn.click()

        assert "Saved" in panel._status.text()
        assert panel._send_btn.isEnabled(), "button re-enabled for retry"


class TestSettingsIntegration:
    def test_feedback_tab_is_visible(self, qapp):
        panel = SettingsPanel(dict(app_main.DEFAULT_SETTINGS))
        names = [panel._tabs.tabText(i) for i in range(panel._tabs.count())]
        assert "Feedback" in names
        idx = names.index("Feedback")
        assert panel._tabs.isTabVisible(idx), "Feedback must be a visible tab"
        assert panel._tabs.tabText(idx + 1) == "About", "Feedback sits before About"

    def test_focus_feedback_tab(self, qapp):
        panel = SettingsPanel(dict(app_main.DEFAULT_SETTINGS))
        panel.focus_feedback_tab()
        assert panel._tabs.currentWidget() is panel._feedback_tab


class TestTrayIntegration:
    @pytest.fixture
    def controller(self, qapp, monkeypatch):
        monkeypatch.setattr(app_main, "resolve_api_key", lambda **kwargs: "")
        monkeypatch.setattr(
            app_main.GhostMindController, "_register_hotkeys", lambda self: None
        )
        ctrl = app_main.GhostMindController(qapp, dict(app_main.DEFAULT_SETTINGS))
        ctrl._update_timer.stop()
        yield ctrl
        ctrl._update_timer.stop()
        ctrl.hotkeys.unregister_all()
        ctrl.overlay.close_event_allowed = True
        ctrl.overlay.close()
        ctrl._tray.hide()
        ctrl.deleteLater()
        qapp.processEvents()

    def test_tray_has_send_feedback_action(self, controller):
        actions = [a.text() for a in controller._tray_menu.actions()]
        assert "Send feedback…" in actions

    def test_tray_action_opens_feedback_tab(self, controller, qapp):
        action = next(
            a for a in controller._tray_menu.actions() if a.text() == "Send feedback…"
        )
        controller.overlay.show()
        action.trigger()
        qapp.processEvents()

        assert controller.overlay.is_settings_open()
        assert controller.overlay._settings_panel._tabs.currentWidget() \
            is controller.overlay._settings_panel._feedback_tab

    def test_flush_worker_wired_on_controller(self, controller):
        assert hasattr(controller, "_flush_feedback_outbox")
        assert controller._outbox_worker is None
