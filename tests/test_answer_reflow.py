"""Tests for size-adaptive answer rendering (reflow) and size-aware token budget."""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import ui.overlay_window as overlay_window
from core.ai_engine import estimate_visible_tokens
from tests.test_window_geometry import BASE_SETTINGS
from ui.answer_panel import _AnswerBlock
from ui.overlay_window import OverlayWindow

LONG_TEXT = " ".join(f"word{i}" for i in range(600))


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _measure(block: _AnswerBlock, width: int) -> int:
    block.resize(width, 200)
    QApplication.processEvents()
    block._recompute_height()
    return block._text.minimumHeight()


@pytest.fixture
def block(qapp):
    b = _AnswerBlock(font_pt=13)
    b.resize(500, 200)
    b.show()
    QApplication.processEvents()
    yield b
    b.close()


class TestAnswerBlockReflow:
    def test_narrower_block_is_taller(self, block):
        block.set_html(f"<p>{LONG_TEXT}</p>")
        wide = _measure(block, 600)
        narrow = _measure(block, 280)
        assert wide > 0
        assert narrow > wide

    def test_remeasure_is_stable(self, block):
        block.set_html(f"<p>{LONG_TEXT}</p>")
        first = _measure(block, 500)
        second = _measure(block, 500)
        assert first == second

    def test_tall_answer_is_not_capped(self, block):
        lines = "<br>".join(f"line {i}" for i in range(200))
        block.set_html(f"<p>{lines}</p>")
        assert _measure(block, 500) > 1400

    def test_resize_triggers_automatic_reflow(self, block):
        block.set_html(f"<p>{LONG_TEXT}</p>")
        wide = _measure(block, 600)
        block.resize(280, 200)
        QTest.qWait(120)  # debounce timer fires and re-measures
        assert block._text.minimumHeight() > wide

    def test_font_change_triggers_remeasure(self, block):
        block.set_html(f"<p>{LONG_TEXT}</p>")
        before = _measure(block, 500)
        block.apply_font_size(26)
        QApplication.processEvents()
        block._recompute_height()
        assert block._text.minimumHeight() > before


class _FakeStreamWorker(QObject):
    chunk_received = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    created: ClassVar[list] = []

    def __init__(self, content, context_type, model_id=None, capacity=None, parent=None):
        super().__init__(parent)
        _FakeStreamWorker.created.append(capacity)

    def isRunning(self) -> bool:
        return False

    def start(self) -> None:
        pass


@pytest.fixture
def overlay(qapp):
    win = OverlayWindow(dict(BASE_SETTINGS), Path("."))
    win.show()
    QApplication.processEvents()
    yield win
    win.close()


class TestStartAiCapacity:
    def test_start_ai_passes_viewport_capacity(self, overlay, monkeypatch):
        _FakeStreamWorker.created.clear()
        monkeypatch.setattr(overlay_window, "AiStreamWorker", _FakeStreamWorker)
        overlay._start_ai("hello", "manual")
        vp = overlay._answer_panel._scroll.viewport()
        expected = estimate_visible_tokens(vp.width(), vp.height(), 13)
        assert _FakeStreamWorker.created == [expected]

    def test_capacity_grows_with_window(self, overlay, monkeypatch):
        _FakeStreamWorker.created.clear()
        monkeypatch.setattr(overlay_window, "AiStreamWorker", _FakeStreamWorker)
        overlay._start_ai("hello", "manual")
        small = _FakeStreamWorker.created[-1]
        overlay._ai_worker = None
        overlay.resize(900, 1100)
        QApplication.processEvents()
        overlay._start_ai("hello", "manual")
        assert _FakeStreamWorker.created[-1] > small
