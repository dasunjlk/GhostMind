"""
Windows auto-start on login via registry.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

APP_NAME = "GhostMind"


def _get_reg_key():
    """Get the Windows Run registry key."""
    try:
        import winreg
        return winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
    except Exception as e:
        logger.warning("Cannot access registry: %s", e)
        return None


def is_autostart_enabled() -> bool:
    """Check if GhostMind is set to auto-start."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False


def enable_autostart() -> bool:
    """Enable auto-start on Windows login."""
    key = _get_reg_key()
    if key is None:
        return False
    try:
        import winreg
        exe = sys.executable
        # If running as a script, use python.exe with the script path
        if getattr(sys, "frozen", False):
            exe = sys.executable
        else:
            exe = f'"{sys.executable}" "{Path(__file__).resolve().parent.parent / "main.py"}"'

        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe)
        winreg.CloseKey(key)
        logger.info("Auto-start enabled")
        return True
    except Exception as e:
        logger.error("Failed to enable auto-start: %s", e)
        return False


def disable_autostart() -> bool:
    """Disable auto-start on Windows login."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
        logger.info("Auto-start disabled")
        return True
    except Exception as e:
        logger.error("Failed to disable auto-start: %s", e)
        return False
