"""Tray icon asset loading (C9): bundled asset preferred, drawn glyph fallback."""
from __future__ import annotations

import sys

import pytest
from PyQt6.QtWidgets import QApplication

import main as app_main


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestTrayIcon:
    def test_loads_bundled_asset_in_source_runs(self, qapp):
        icon = app_main._create_tray_icon()
        assert not icon.isNull()
        sizes = icon.availableSizes()
        assert any(s.width() >= 256 for s in sizes), (
            "the drawn fallback is only 64px; a 256px layer proves the "
            "icon_256.png asset was loaded"
        )

    def test_drawn_fallback_when_assets_missing(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        icon = app_main._create_tray_icon()
        assert not icon.isNull()
        sizes = icon.availableSizes()
        assert sizes and all(s.width() <= 64 for s in sizes), (
            "without the asset files the drawn 64px glyph is the only source"
        )
