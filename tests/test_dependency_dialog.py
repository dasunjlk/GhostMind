"""Tests for non-blocking startup dependency warnings."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from PyQt6.QtWidgets import QApplication

import main as app_main
from ui.dependency_banner import DependencyBanner
from ui.overlay_window import OverlayWindow

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


class TestDependencyBanner:
    def test_tesseract_warning_shows_install_action(self, qapp):
        banner = DependencyBanner()
        banner.show_warnings([TESSERACT_MSG])
        assert not banner.isHidden()
        assert "Tesseract OCR not found" in banner._label.text()
        assert not banner._install_btn.isHidden()

    def test_install_button_emits_request(self, qapp):
        banner = DependencyBanner()
        banner.show_warnings([TESSERACT_MSG])
        calls = []
        banner.install_tesseract_requested.connect(lambda: calls.append(True))
        banner._install_btn.click()
        assert calls == [True]

    def test_plain_warning_hides_install_action(self, qapp):
        banner = DependencyBanner()
        banner.show_warnings([PLAIN_MSG])
        assert not banner.isHidden()
        assert banner._install_btn.isHidden()

    def test_settings_and_dismiss_actions(self, qapp):
        banner = DependencyBanner()
        banner.show_warnings([PLAIN_MSG])
        calls = []
        banner.settings_requested.connect(lambda: calls.append("settings"))
        banner.dismissed.connect(lambda: calls.append("dismissed"))
        banner._settings_btn.click()
        banner._dismiss_btn.click()
        assert calls == ["settings", "dismissed"]
        assert banner.isHidden()

    def test_empty_warnings_keep_banner_hidden(self, qapp):
        banner = DependencyBanner()
        banner.show_warnings([])
        assert banner.isHidden()


class TestOverlayDependencyBanner:
    def test_settings_button_opens_settings_and_hides_banner(self, qapp):
        overlay = OverlayWindow(dict(app_main.DEFAULT_SETTINGS), Path("."))
        try:
            overlay.show_dependency_warnings([TESSERACT_MSG])
            assert not overlay._dep_banner.isHidden()
            overlay._dep_banner._settings_btn.click()
            assert overlay._stack.currentIndex() == 1
            assert overlay._dep_banner.isHidden()
        finally:
            overlay.close()

    def test_install_action_is_forwarded_from_overlay(self, qapp):
        overlay = OverlayWindow(dict(app_main.DEFAULT_SETTINGS), Path("."))
        calls = []
        overlay.install_tesseract_requested.connect(lambda: calls.append(True))
        try:
            overlay.show_dependency_warnings([TESSERACT_MSG])
            overlay._dep_banner._install_btn.click()
            assert calls == [True]
        finally:
            overlay.close()


class TestTesseractAction:
    def test_controller_opens_download_page(self, qapp):
        with mock.patch.object(app_main.QDesktopServices, "openUrl") as open_url:
            app_main.GhostMindController._open_tesseract_download(None)
        open_url.assert_called_once()
        assert app_main.TESSERACT_URL in open_url.call_args.args[0].toString()


class TestStartupWarnings:
    def test_missing_api_key_is_not_a_warning(self, monkeypatch):
        """First-run users have no key yet; startup must not nag them."""
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        warnings = app_main.check_dependencies()
        assert not any("API key" in warning for warning in warnings)
