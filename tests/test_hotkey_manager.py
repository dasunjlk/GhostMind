"""Tests for utils/hotkey_manager.py — hotkey signal wiring."""
from __future__ import annotations

import pytest

# Skip all tests if PyQt6 is not available (headless CI)
pytestmark = pytest.mark.skipif(
    not pytest.importorskip("PyQt6", reason="PyQt6 not installed"),
    reason="PyQt6 required",
)


class TestHotkeyManagerSignals:
    """Test that HotkeyManager has the expected signals defined."""

    def test_has_toggle_visibility_signal(self):
        from utils.hotkey_manager import HotkeyManager
        assert hasattr(HotkeyManager, "toggle_visibility")

    def test_has_trigger_screen_scan_signal(self):
        from utils.hotkey_manager import HotkeyManager
        assert hasattr(HotkeyManager, "trigger_screen_scan")

    def test_has_clear_answers_signal(self):
        from utils.hotkey_manager import HotkeyManager
        assert hasattr(HotkeyManager, "clear_answers")

    def test_has_toggle_subtitles_signal(self):
        from utils.hotkey_manager import HotkeyManager
        assert hasattr(HotkeyManager, "toggle_subtitles")

    def test_has_export_transcript_signal(self):
        from utils.hotkey_manager import HotkeyManager
        assert hasattr(HotkeyManager, "export_transcript")


class TestHotkeyManagerMethods:
    """Test that HotkeyManager has the expected methods."""

    def test_has_update_hotkeys(self):
        from utils.hotkey_manager import HotkeyManager
        assert hasattr(HotkeyManager, "update_hotkeys")
        assert callable(HotkeyManager.update_hotkeys)

    def test_has_unregister_all(self):
        from utils.hotkey_manager import HotkeyManager
        assert hasattr(HotkeyManager, "unregister_all")
        assert callable(HotkeyManager.unregister_all)


class TestHotkeyManagerInit:
    """Test HotkeyManager initialization (no keyboard library needed)."""

    def test_init_creates_instance(self):
        from utils.hotkey_manager import HotkeyManager
        hm = HotkeyManager()
        assert hm is not None

    def test_init_empty_handles(self):
        from utils.hotkey_manager import HotkeyManager
        hm = HotkeyManager()
        assert hm._handles == []
        assert hm._registered == {}

    def test_unregister_all_on_empty(self):
        from utils.hotkey_manager import HotkeyManager
        hm = HotkeyManager()
        # Should not raise
        hm.unregister_all()
        assert hm._handles == []
