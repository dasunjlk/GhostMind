"""
Windows stealth window attributes: Alt+Tab / taskbar hiding, optional click-through,
and exclusion from screen capture (DWM cloak + display affinity).
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

try:
    import win32con
    import win32gui
except ImportError:  # pragma: no cover
    win32con = None  # type: ignore
    win32gui = None  # type: ignore

logger = logging.getLogger(__name__)

# --- user32 ---
user32 = ctypes.windll.user32

GWL_EXSTYLE = -20

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000

LWA_ALPHA = 0x00000002

# Windows 10 2004+ — exclude window from screen capture / sharing
WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011

# DWM attributes (Desktop Window Manager)
DWMWA_CLOAK = 14

SetWindowDisplayAffinity = user32.SetWindowDisplayAffinity
SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
SetWindowDisplayAffinity.restype = wintypes.BOOL

SetLayeredWindowAttributes = user32.SetLayeredWindowAttributes
SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND,
    wintypes.COLORREF,
    ctypes.c_byte,
    wintypes.DWORD,
]
SetLayeredWindowAttributes.restype = wintypes.BOOL

try:
    dwmapi = ctypes.windll.dwmapi
    _DwmSetWindowAttribute = dwmapi.DwmSetWindowAttribute
    _DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _DwmSetWindowAttribute.restype = wintypes.HRESULT
except OSError:  # pragma: no cover
    dwmapi = None
    _DwmSetWindowAttribute = None


def _set_dwm_cloak(hwnd: int, cloak: bool) -> None:
    if _DwmSetWindowAttribute is None:
        return
    try:
        value = ctypes.c_int(1 if cloak else 0)
        hr = _DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_CLOAK),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        if hr != 0:
            logger.debug("DwmSetWindowAttribute(DWMWA_CLOAK) returned %s", hr)
    except OSError as e:
        logger.debug("DWM cloak not applied: %s", e)


def _set_capture_exclusion(hwnd: int, exclude: bool) -> None:
    try:
        aff = WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE
        if not SetWindowDisplayAffinity(wintypes.HWND(hwnd), aff):
            logger.debug("SetWindowDisplayAffinity failed for hwnd=%s", hwnd)
    except OSError as e:
        logger.debug("SetWindowDisplayAffinity error: %s", e)


def _ctypes_get_exstyle(hwnd: int) -> int:
    try:
        get_fn = user32.GetWindowLongPtrW
        set_fn = user32.SetWindowLongPtrW
    except AttributeError:  # pragma: no cover
        get_fn = user32.GetWindowLongW
        set_fn = user32.SetWindowLongW
    return int(get_fn(wintypes.HWND(hwnd), GWL_EXSTYLE))


def _ctypes_set_exstyle(hwnd: int, style: int) -> None:
    try:
        set_fn = user32.SetWindowLongPtrW
    except AttributeError:  # pragma: no cover
        set_fn = user32.SetWindowLongW
    set_fn(wintypes.HWND(hwnd), GWL_EXSTYLE, style)


def _apply_extended_styles(hwnd: int, click_through: bool) -> None:
    if win32gui is None or win32con is None:
        style = _ctypes_get_exstyle(hwnd)
        style |= WS_EX_TOOLWINDOW | WS_EX_LAYERED
        style &= ~WS_EX_APPWINDOW
        if click_through:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        _ctypes_set_exstyle(hwnd, style)
        return

    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    style |= WS_EX_TOOLWINDOW | WS_EX_LAYERED
    style &= ~WS_EX_APPWINDOW
    if click_through:
        style |= WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)


def apply_stealth(hwnd: int, click_through: bool = False, dwm_cloak: bool = False) -> None:
    """
    Apply all stealth attributes to a native window handle.

    - Hides from Alt+Tab and taskbar (WS_EX_TOOLWINDOW, no WS_EX_APPWINDOW).
    - WS_EX_LAYERED for layered composition; WS_EX_TRANSPARENT when click_through.
    - SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) to exclude from capture/sharing
      while keeping the overlay visible locally (Win10 2004+).
    - Optional ``dwm_cloak=True`` calls DWMWA_CLOAK (normally hides the window from the
      local user; off by default).
    """
    if not hwnd:
        return
    try:
        _apply_extended_styles(hwnd, click_through)
        if dwm_cloak:
            _set_dwm_cloak(hwnd, True)
        _set_capture_exclusion(hwnd, True)
    except OSError as e:
        logger.warning("apply_stealth failed: %s", e)
