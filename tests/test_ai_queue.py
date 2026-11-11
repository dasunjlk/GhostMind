"""Tests for the sequential AI request queue (C4)."""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

import ui.overlay_window as overlay_window
from core.ai_engine import estimate_visible_tokens
from tests.test_window_geometry import BASE_SETTINGS
from ui.overlay_window import (
    AI_QUEUE_OVERFLOW_MESSAGE,
    MAX_AI_QUEUE,
    OverlayWindow,
)


class _FakeAiWorker(QObject):
    """Stand-in for AiStreamWorker; records requests and emits on demand."""

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
        self.capacity = capacity
        self.history = history
        _FakeAiWorker.created.append(self)

    def isRunning(self) -> bool:
        return True

    def start(self) -> None:
        pass


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
    QApplication.processEvents()
    yield win
    win.close()


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


def _answers(overlay) -> list[str]:
    return [block._raw_markdown for block in overlay._answer_panel._blocks]


class TestFifoQueue:
    def test_three_rapid_asks_are_answered_in_order(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        for question in ("Q1", "Q2", "Q3"):
            _ask(overlay, question)

        assert [worker.content for worker in _FakeAiWorker.created] == ["Q1"]
        assert len(overlay._ai_queue) == 2

        _answer(_FakeAiWorker.created[0], "A1")
        assert [worker.content for worker in _FakeAiWorker.created] == ["Q1", "Q2"]

        _answer(_FakeAiWorker.created[1], "A2")
        _answer(_FakeAiWorker.created[2], "A3")

        assert [worker.content for worker in _FakeAiWorker.created] == [
            "Q1",
            "Q2",
            "Q3",
        ]
        assert _answers(overlay) == ["A1", "A2", "A3"]
        assert overlay._active_worker_id is None
        assert not overlay._ai_queue

    def test_queue_label_tracks_waiting_requests(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        _ask(overlay, "Q1")
        _ask(overlay, "Q2")

        assert overlay._queue_label.isVisible() is True
        assert overlay._queue_label.text() == "1 queued…"

        _answer(_FakeAiWorker.created[0], "A1")

        assert overlay._queue_label.isVisible() is False
        assert overlay._queue_label.text() == "0 queued…"

    def test_overflow_keeps_text_and_shows_inline_error(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        for index in range(MAX_AI_QUEUE):
            _ask(overlay, f"Q{index + 1}")

        assert len(overlay._ai_queue) == MAX_AI_QUEUE - 1

        _ask(overlay, "Q5")

        assert overlay._ask_input.text() == "Q5", "rejected text must not be lost"
        assert len(overlay._ai_queue) == MAX_AI_QUEUE - 1
        assert any(
            AI_QUEUE_OVERFLOW_MESSAGE in block._text.toPlainText()
            for block in overlay._answer_panel._blocks
        )

    def test_capacity_is_measured_when_request_starts(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        overlay.resize(600, 700)
        QApplication.processEvents()
        _ask(overlay, "Q1")
        first_capacity = _FakeAiWorker.created[0].capacity

        overlay.resize(900, 1100)
        QApplication.processEvents()
        _ask(overlay, "Q2")

        assert len(_FakeAiWorker.created) == 1, "second request waits for the first"
        assert _FakeAiWorker.created[0].capacity == first_capacity

        _answer(_FakeAiWorker.created[0], "A1")

        viewport = overlay._answer_panel._scroll.viewport()
        expected = estimate_visible_tokens(viewport.width(), viewport.height(), 13)
        assert _FakeAiWorker.created[-1].capacity == expected
        assert _FakeAiWorker.created[-1].capacity > first_capacity


class TestStaleWorkerIsolation:
    def test_late_signals_after_clear_paint_nothing(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        _ask(overlay, "Q1")
        worker = _FakeAiWorker.created[0]
        overlay.clear_answers()

        assert overlay._answer_panel._blocks == []

        worker.chunk_received.emit("late chunk")
        worker.finished_ok.emit()
        worker.failed.emit("late failure")

        assert overlay._answer_panel._blocks == []
        assert overlay._answer_panel._stream_buffer == ""

        worker.finished.emit()
        assert overlay._active_worker_id is None

    def test_stale_worker_cannot_bleed_into_next_answer(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)

        _ask(overlay, "Q1")
        _ask(overlay, "Q2")
        first = _FakeAiWorker.created[0]

        _answer(first, "A1")
        second = _FakeAiWorker.created[1]

        first.chunk_received.emit("stale chunk")
        first.finished_ok.emit()
        first.failed.emit("stale failure")

        _answer(second, "A2")

        assert _answers(overlay) == ["A1", "A2"]
        assert all("stale" not in answer for answer in _answers(overlay))

    def test_manual_bubble_is_added_only_after_enqueue(self, overlay, monkeypatch):
        _install_fake_ai(overlay, monkeypatch)
        bubbles: list[str] = []
        monkeypatch.setattr(
            overlay._answer_panel,
            "add_user_message",
            lambda text: bubbles.append(text),
        )

        for index in range(MAX_AI_QUEUE):
            _ask(overlay, f"Q{index + 1}")

        _ask(overlay, "Q5")

        assert bubbles == ["Q1", "Q2", "Q3", "Q4"]
        assert overlay._ask_input.text() == "Q5"
