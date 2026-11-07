"""Bundled Tesseract resolution (C11): QA hook, frozen path, dependency check.

All tests are offline — the dependency-check test fakes the version probe so
no real tesseract.exe ever runs.
"""
from __future__ import annotations

import sys

import pytest

import core.screen_reader as screen_reader
import main as app_main


@pytest.fixture
def pytesseract_cmd_guard():
    """Save/restore pytesseract.tesseract_cmd so overrides never leak."""
    import pytesseract

    saved = pytesseract.pytesseract.tesseract_cmd
    yield
    pytesseract.pytesseract.tesseract_cmd = saved


@pytest.fixture
def fake_bundle(tmp_path):
    """A directory holding a fake tesseract.exe (never executed)."""
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"MZ")
    return tmp_path, exe


class TestBundledResolution:
    def test_env_override_points_pytesseract_at_bundle(
        self, monkeypatch, fake_bundle, pytesseract_cmd_guard
    ):
        root, exe = fake_bundle
        monkeypatch.setenv("GHOSTMIND_TESSERACT_DIR", str(root))

        result = screen_reader.configure_tesseract_path()

        assert result == exe
        import pytesseract

        assert pytesseract.pytesseract.tesseract_cmd == str(exe)

    def test_wrong_override_wins_over_detection(
        self, monkeypatch, tmp_path, pytesseract_cmd_guard
    ):
        """A bad QA override must not silently fall back to other sources."""
        monkeypatch.setenv("GHOSTMIND_TESSERACT_DIR", str(tmp_path / "nope"))

        assert screen_reader.configure_tesseract_path() is None

    def test_frozen_build_finds_exe_sibling_dir(
        self, monkeypatch, tmp_path, pytesseract_cmd_guard
    ):
        monkeypatch.delenv("GHOSTMIND_TESSERACT_DIR", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "ghostmind.exe"))
        exe = tmp_path / "tesseract" / "tesseract.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"MZ")

        assert screen_reader.configure_tesseract_path() == exe

    def test_frozen_build_without_bundle_keeps_path_lookup(
        self, monkeypatch, tmp_path, pytesseract_cmd_guard
    ):
        monkeypatch.delenv("GHOSTMIND_TESSERACT_DIR", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "ghostmind.exe"))

        assert screen_reader.configure_tesseract_path() is None

    def test_source_run_without_override_keeps_path_lookup(
        self, monkeypatch, pytesseract_cmd_guard
    ):
        monkeypatch.delenv("GHOSTMIND_TESSERACT_DIR", raising=False)
        monkeypatch.setattr(sys, "frozen", False, raising=False)

        assert screen_reader.configure_tesseract_path() is None


class TestDependencyCheckWithBundle:
    def test_bundled_tesseract_produces_no_warning(
        self, monkeypatch, fake_bundle
    ):
        import pytesseract

        root, _exe = fake_bundle
        monkeypatch.setenv("GHOSTMIND_TESSERACT_DIR", str(root))
        monkeypatch.setattr(
            pytesseract, "get_tesseract_version", lambda: "5.3.0.20240331"
        )

        warnings = app_main.check_dependencies()

        assert not any("Tesseract OCR not found" in w for w in warnings), (
            "installed builds ship Tesseract — the startup banner must not appear"
        )

    def test_source_run_still_warns_without_tesseract(self, monkeypatch):
        import pytesseract

        monkeypatch.delenv("GHOSTMIND_TESSERACT_DIR", raising=False)
        monkeypatch.setattr(sys, "frozen", False, raising=False)

        def _boom():
            raise pytesseract.TesseractNotFoundError()

        monkeypatch.setattr(pytesseract, "get_tesseract_version", _boom)

        warnings = app_main.check_dependencies()

        assert any("Tesseract OCR not found" in w for w in warnings), (
            "source runs without Tesseract keep the install guidance"
        )
