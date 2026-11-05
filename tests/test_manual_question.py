"""Tests for F-01 (S-04) manual question input box."""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QPushButton

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


class _FakeAiWorker(QObject):
    """Stand-in for AiStreamWorker: records history and emits synchronously."""

    chunk_received = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    created: ClassVar[list] = []

    def __init__(
        self,
        content,
        context_type,
        model_id=None,
        capacity=None,
        base_url=None,
        api_key=None,
        history=None,
        parent=None,
    ):
        super().__init__(parent)
        self.content = content
        self.context_type = context_type
        self.history = history
        _FakeAiWorker.created.append(self)

    def isRunning(self) -> bool:
        return False

    def start(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_fake_ai_worker():
    _FakeAiWorker.created.clear()
    yield
    _FakeAiWorker.created.clear()


def _install_fake_ai(overlay, monkeypatch) -> None:
    monkeypatch.setattr(overlay_window, "AiStreamWorker", _FakeAiWorker)
    monkeypatch.setattr(overlay_window, "resolve_api_key", lambda **kwargs: "sk-test")


def _ask(overlay, text: str) -> None:
    overlay._ask_input.setText(text)
    overlay._send_manual_question()


def _answer(worker, text: str) -> None:
    worker.chunk_received.emit(text)
    worker.finished_ok.emit()
    worker.finished.emit()


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

    def test_send_while_busy_is_queued(self, overlay, monkeypatch):
        """A second ask must queue instead of being rejected."""
        _install_fake_ai(overlay, monkeypatch)

        _ask(overlay, "first question")
        _ask(overlay, "second question")

        assert overlay._ask_input.text() == "", "accepted queue entry clears the box"
        assert len(_FakeAiWorker.created) == 1, "only one worker runs at a time"
        assert len(overlay._ai_queue) == 1, "second question waits in the queue"

        _answer(_FakeAiWorker.created[0], "first answer")

        assert len(_FakeAiWorker.created) == 2
        assert _FakeAiWorker.created[-1].content == "second question"

    def test_empty_input_does_nothing(self, overlay, monkeypatch):
        sent: list = []
        monkeypatch.setattr(OverlayWindow, "_start_ai", lambda self, c, t: sent.append(1))
        QTest.keyClick(overlay._ask_input, Qt.Key.Key_Return)
        assert sent == []

    def test_focus_question_input(self, overlay):
        overlay._stack.setCurrentIndex(1)  # settings page
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


class TestSessionMemoryIntegration:
    def test_second_prompt_contains_the_first_exchange(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        _ask(overlay, "What is 2+2?")
        _answer(_FakeAiWorker.created[-1], "4")

        _ask(overlay, "And 3+3?")

        assert _FakeAiWorker.created[-1].history == [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]

    def test_failed_answer_is_not_remembered(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        _ask(overlay, "bad question")
        worker = _FakeAiWorker.created[-1]
        worker.chunk_received.emit("partial")
        worker.failed.emit("network error")

        assert overlay._memory.is_empty() is True

        _ask(overlay, "next question")
        assert _FakeAiWorker.created[-1].history is None

    def test_screen_scan_exchange_is_remembered(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        overlay._start_ai("OCR text", "screen")
        _answer(_FakeAiWorker.created[-1], "screen answer")

        assert overlay._memory.window() == [
            {"role": "user", "content": "OCR text"},
            {"role": "assistant", "content": "screen answer"},
        ]

        _ask(overlay, "follow-up")
        assert _FakeAiWorker.created[-1].history == [
            {"role": "user", "content": "OCR text"},
            {"role": "assistant", "content": "screen answer"},
        ]

    def test_meeting_context_is_not_remembered_or_injected(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        overlay._start_ai("meeting transcript", "meeting_audio")
        _answer(_FakeAiWorker.created[-1], "meeting answer")

        assert overlay._memory.is_empty() is True

        overlay._memory.add_question("manual question", "manual")
        overlay._memory.add_answer("manual answer")
        overlay._start_ai("another transcript", "meeting_audio")

        assert _FakeAiWorker.created[-1].history is None

    def test_clear_button_forgets_memory_and_has_tooltip(self, overlay):
        overlay._memory.add_question("question", "manual")
        overlay._memory.add_answer("answer")
        clear_btn = next(
            button
            for button in overlay._answer_panel.findChildren(QPushButton)
            if button.text() == "Clear"
        )

        assert "forgets" in clear_btn.toolTip().lower()
        clear_btn.click()

        assert overlay._memory.is_empty() is True

    def test_clear_answers_forgets_memory(self, overlay):
        overlay._memory.add_question("question", "manual")
        overlay._memory.add_answer("answer")

        overlay.clear_answers()

        assert overlay._memory.is_empty() is True

    def test_clearing_mid_stream_drops_the_pending_answer(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        _ask(overlay, "question")
        worker = _FakeAiWorker.created[-1]
        worker.chunk_received.emit("partial")
        overlay.clear_answers()
        worker.finished_ok.emit()

        assert overlay._memory.is_empty() is True
