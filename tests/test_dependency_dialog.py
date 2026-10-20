"""Tests for the startup dependency dialog (Tesseract one-click install, R-01)."""
from __future__ import annotations

from unittest import mock

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

import main as app_main

TESSERACT_MSG = (
    "Tesseract OCR not found.\n"
    "  Screen scanning (OCR) will not work.\n"
    "  Install: choco install tesseract"
)

PLAIN_MSG = "groq package not installed.\n  AI answers will not work."


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _find_button(box: QMessageBox, text: str):
    for btn in box.buttons():
        if btn.text() == text:
            return btn
    return None


class TestDependencyDialog:
    def test_tesseract_message_adds_install_button(self, qapp):
        box = app_main._dependency_dialog(TESSERACT_MSG)
        btn = _find_button(box, "Install Tesseract OCR")
        assert btn is not None, "Install button must appear for Tesseract warnings"
        assert box.icon() == QMessageBox.Icon.Warning

    def test_install_button_opens_download_page(self, qapp):
        box = app_main._dependency_dialog(TESSERACT_MSG)
        btn = _find_button(box, "Install Tesseract OCR")
        assert btn is not None
        with mock.patch.object(app_main.QDesktopServices, "openUrl") as open_url:
            btn.click()
        open_url.assert_called_once()
        assert app_main.TESSERACT_URL in open_url.call_args.args[0].toString()

    def test_plain_message_has_no_install_button(self, qapp):
        box = app_main._dependency_dialog(PLAIN_MSG)
        assert _find_button(box, "Install Tesseract OCR") is None
        # Still a standard warning box with an OK to dismiss.
        ok = box.button(QMessageBox.StandardButton.Ok)
        assert ok is not None
