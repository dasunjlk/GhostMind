"""Tests for the header Scan button (same action as the screen-scan hotkey)."""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

import ui.overlay_window as overlay_window
from tests.test_window_geometry import BASE_SETTINGS
from ui.overlay_window import OverlayWindow


class _FakeScanWorker(QObject):
    """Stand-in for ScreenScanWorker: never really scans, reports as running."""

    finished = pyqtSignal()
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    started: ClassVar[list] = []

    def __init__(self, monitor_id: int) -> None:
        super().__init__()
        self.monitor_id = monitor_id

    def start(self) -> None:
        _FakeScanWorker.started.append(self)

    def isRunning(self) -> bool:
        return True


class _FakeAiWorker(QObject):
    """Stand-in for AiStreamWorker: records the queued scan request."""

    chunk_received = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    created: ClassVar[list] = []

    def __init__(self, content, context_type, **kwargs) -> None:
        super().__init__()
        self.content = content
        self.context_type = context_type
        _FakeAiWorker.created.append(self)

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
    yield win
    win.close()


@pytest.fixture(autouse=True)
def _reset_fake_worker():
    _FakeScanWorker.started.clear()
    _FakeAiWorker.created.clear()
    yield
    _FakeScanWorker.started.clear()
    _FakeAiWorker.created.clear()


class TestScanButton:
    def test_button_exists_in_header(self, overlay):
        assert isinstance(overlay._btn_scan, QPushButton)
        assert overlay._btn_scan.objectName() == "scanBtn"
        assert overlay._btn_scan.isEnabled()

    def test_button_click_triggers_scan(self, overlay, monkeypatch):
        monkeypatch.setattr(overlay_window, "ScreenScanWorker", _FakeScanWorker)

        QTest.mouseClick(overlay._btn_scan, Qt.MouseButton.LeftButton)

        assert len(_FakeScanWorker.started) == 1, "click must start a scan worker"
        assert overlay._tabs.currentIndex() == 0, "Answers tab must be focused"

    def test_scan_disables_button_until_finished(self, overlay, monkeypatch):
        monkeypatch.setattr(overlay_window, "ScreenScanWorker", _FakeScanWorker)

        overlay.trigger_screen_scan()
        assert len(_FakeScanWorker.started) == 1
        assert not overlay._btn_scan.isEnabled(), "button must be disabled during scan"

        # Re-entrant trigger (hotkey spam) must not start a second worker
        overlay.trigger_screen_scan()
        assert len(_FakeScanWorker.started) == 1

        # Worker finishes -> button re-enabled
        _FakeScanWorker.started[0].finished.emit()
        assert overlay._btn_scan.isEnabled()

    def test_scan_result_goes_through_the_ai_queue(self, overlay, monkeypatch):
        monkeypatch.setattr(overlay_window, "ScreenScanWorker", _FakeScanWorker)
        monkeypatch.setattr(overlay_window, "AiStreamWorker", _FakeAiWorker)
        monkeypatch.setattr(
            overlay_window,
            "resolve_api_key",
            lambda **kwargs: "sk-test",
        )

        overlay.trigger_screen_scan()
        _FakeScanWorker.started[0].finished_ok.emit("OCR text")

        assert len(_FakeAiWorker.created) == 1
        assert _FakeAiWorker.created[0].content == "OCR text"
        assert _FakeAiWorker.created[0].context_type == "screen"
