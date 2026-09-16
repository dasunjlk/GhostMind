"""Tests for F-01 (S-04) manual question input box."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit

import ui.overlay_window as overlay_window
from core.ai_engine import build_system_prompt, build_user_message
from tests.test_window_geometry import BASE_SETTINGS
from ui.overlay_window import OverlayWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def overlay(qapp):
    win = OverlayWindow(dict(BASE_SETTINGS), Path("."))
    win.show()
    yield win
    win.close()


class TestManualPromptRouting:
    def test_system_prompt_is_plain_base(self):
        from core.ai_engine import BASE_SYSTEM

        p = build_system_prompt("manual", "What is 2+2?")
        assert p == BASE_SYSTEM, "manual must not add screen/meeting framing"

    def test_system_prompt_differs_from_screen(self):
        assert build_system_prompt("manual", "x") != build_system_prompt(
            "screen", "x"
        ), "manual and screen must route differently"

    def test_user_message_is_raw_content(self):
        assert build_user_message("manual", "What is 2+2?") == "What is 2+2?"

    def test_other_contexts_unchanged(self):
        assert build_user_message("meeting_question", "q?") != "q?"
        assert build_user_message("screen", "t") != "t"


class TestAskRowUI:
    def test_row_and_widgets_exist(self, overlay):
        assert overlay._ask_row is not None
        assert isinstance(overlay._ask_input, QLineEdit)
        assert overlay._ask_btn.isEnabled()

    def test_enter_sends_and_clears_box(self, overlay, monkeypatch):
        """Accepted send: input empties so the next question can be typed."""
        sent: list = []

        def fake_start_ai(self, content, context_type):
            sent.append((content, context_type))

        monkeypatch.setattr(OverlayWindow, "_start_ai", fake_start_ai)
        QTest.keyClicks(overlay._ask_input, "What is the capital of France?")
        QTest.keyClick(overlay._ask_input, Qt.Key.Key_Return)
        assert sent == [("What is the capital of France?", "manual")]
        assert overlay._ask_input.text() == "", "box must be empty after sending"

    def test_user_message_bubble_shown_for_chat(self, overlay, monkeypatch):
        """Typed messages echo as a user bubble; scan flows do not."""
        from PyQt6.QtCore import pyqtSignal
        from ui.answer_panel import AnswerPanel

        calls: list = []
        monkeypatch.setattr(
            AnswerPanel, "add_user_message", lambda self, t: calls.append(t)
        )

        monkeypatch.setattr(OverlayWindow, "_start_ai", lambda self, c, t: None)
        QTest.keyClicks(overlay._ask_input, "hello there")
        QTest.keyClick(overlay._ask_input, Qt.Key.Key_Return)
        assert calls == ["hello there"], "chat send must add a user bubble"

        # Scan flow: bubble must NOT appear
        class _FakeScanWorker(QObject):
            finished = pyqtSignal()
            finished_ok = pyqtSignal(str)
            failed = pyqtSignal(str)

            def __init__(self, monitor_id: int) -> None:
                super().__init__()

            def start(self) -> None:
                pass

        monkeypatch.setattr(overlay_window, "ScreenScanWorker", _FakeScanWorker)
        calls.clear()
        overlay.trigger_screen_scan()
        assert calls == [], "scan flow must not add a user bubble"

    def test_send_rejected_keeps_text(self, overlay):
        """Busy (another answer streaming): typed text must not be lost."""

        class _BusyWorker(QObject):
            def isRunning(self) -> bool:
                return True

        overlay._ai_worker = _BusyWorker()  # type: ignore[assignment]
        QTest.keyClicks(overlay._ask_input, "second question")
        QTest.keyClick(overlay._ask_input, Qt.Key.Key_Return)
        assert overlay._ask_input.text() == "second question", "text kept when rejected"

    def test_empty_input_does_nothing(self, overlay, monkeypatch):
        sent: list = []
        monkeypatch.setattr(OverlayWindow, "_start_ai", lambda self, c, t: sent.append(1))
        QTest.keyClick(overlay._ask_input, Qt.Key.Key_Return)
        assert sent == []

    def test_focus_question_input(self, overlay):
        overlay._stack.setCurrentIndex(1)  # settings page
        overlay._tabs.setCurrentIndex(1)  # subtitles tab
        overlay.focus_question_input()
        assert overlay._tabs.currentIndex() == 0
        # The window's in-focus widget must be the input (independent of WM activation)
        assert overlay.focusWidget() is overlay._ask_input


class TestAskHotkey:
    def test_ask_hotkey_registered_and_connected(self, qapp, monkeypatch):
        from utils.hotkey_manager import HotkeyManager

        registered: list = []
        monkeypatch.setattr(
            "utils.hotkey_manager.keyboard",
            type("M", (), {"add_hotkey": staticmethod(lambda c, cb, suppress=False: registered.append(c) or object()),
                           "remove_hotkey": staticmethod(lambda h: None)})(),
        )
        hm = HotkeyManager()
        seen: list = []
        hm.ask_question.connect(lambda: seen.append(1))
        hm.update_hotkeys("ctrl+shift+g", "ctrl+shift+s", "ctrl+shift+c",
                          "ctrl+shift+t", "ctrl+shift+e", "ctrl+shift+x",
                          ask="ctrl+shift+q")
        assert "ctrl+shift+q" in registered

        hm._registered["ctrl+shift+q"]()
        assert seen == [1], "firing the registered combo must emit ask_question"

    def test_default_settings_contain_ask_hotkey(self):
        import importlib

        import main

        importlib.reload(main)
        hk = main.DEFAULT_SETTINGS["hotkeys"]
        assert hk["ask_question"] == "ctrl+shift+q"


class TestSettingsRoundTrip:
    def test_ask_field_loaded_and_saved(self, qapp):
        from ui.settings_panel import SettingsPanel

        data = dict(BASE_SETTINGS)
        panel = SettingsPanel(data)
        assert panel._hk_ask.text() == "ctrl+shift+q"
        out = panel.collect_data()
        assert out["hotkeys"]["ask_question"] == "ctrl+shift+q"

    def test_custom_value_round_trips(self, qapp):
        from ui.settings_panel import SettingsPanel

        data = dict(BASE_SETTINGS)
        data["hotkeys"] = dict(BASE_SETTINGS["hotkeys"])
        data["hotkeys"]["ask_question"] = "ctrl+alt+f9"
        panel = SettingsPanel(data)
        assert panel._hk_ask.text() == "ctrl+alt+f9"
        assert panel.collect_data()["hotkeys"]["ask_question"] == "ctrl+alt+f9"
