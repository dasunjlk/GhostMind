"""
Multi-monitor capture (mss), OCR (pytesseract), window context detection, and optional OpenCV preprocessing.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import mss
import mss.tools
import numpy as np
from PIL import Image
from PyQt6.QtCore import QObject, pyqtSignal, QThread

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None  # type: ignore


def get_active_window_title() -> str:
    """Return the title of the current foreground window on Windows."""
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            title = win32gui.GetWindowText(hwnd).strip()
            # Ignore our own overlay window if it was foreground
            if "ghostmind" not in title.lower():
                return title
    except Exception as e:
        logger.debug("Failed to get foreground window title: %s", e)
    return ""


def detect_meeting_app() -> Optional[str]:
    """Detect if a meeting application (Zoom, Meet, Teams, Webex, Discord) is active or running."""
    fg = get_active_window_title().lower()
    if "zoom" in fg:
        return "Zoom"
    if "meet" in fg or "meet.google.com" in fg:
        return "Google Meet"
    if "teams" in fg:
        return "Microsoft Teams"
    if "webex" in fg:
        return "Cisco Webex"
    if "discord" in fg:
        return "Discord"

    try:
        import win32gui
        found: List[str] = []

        def enum_cb(hwnd: int, _: Any) -> None:
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd).lower()
                if "zoom meeting" in t or (t.startswith("zoom") and "zoom" not in found):
                    found.append("Zoom")
                elif "meet -" in t or "google meet" in t:
                    found.append("Google Meet")
                elif "microsoft teams" in t:
                    found.append("Microsoft Teams")
                elif "webex" in t:
                    found.append("Cisco Webex")

        win32gui.EnumWindows(enum_cb, None)
        if found:
            return found[0]
    except Exception as e:
        logger.debug("Meeting app window enumeration error: %s", e)

    return None


def get_monitors() -> List[Dict[str, Any]]:
    """Return connected monitors as dicts: id, name, width, height, left, top."""
    out: List[Dict[str, Any]] = []
    with mss.mss() as sct:
        for i, mon in enumerate(sct.monitors):
            if i == 0:
                continue  # virtual "all in one"
            left = int(mon["left"])
            top = int(mon["top"])
            w = int(mon["width"])
            h = int(mon["height"])
            out.append(
                {
                    "id": i,
                    "name": f"Monitor {i}",
                    "width": w,
                    "height": h,
                    "x": left,
                    "y": top,
                }
            )
    return out


def capture_screen(monitor_id: int) -> Image.Image:
    with mss.mss() as sct:
        if monitor_id < 0 or monitor_id >= len(sct.monitors):
            monitor_id = 1 if len(sct.monitors) > 1 else 0
        region = sct.monitors[monitor_id]
        raw = sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return img


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    if cv2 is None:
        return img
    try:
        arr = np.array(img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        thr = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        return Image.fromarray(thr)
    except Exception as e:
        logger.debug("OCR preprocess skipped: %s", e)
        return img


def extract_text(image: Image.Image, preprocess: bool = True) -> str:
    if pytesseract is None:
        raise RuntimeError(
            "pytesseract is not installed. "
            "Install it with: pip install pytesseract\n"
            "You also need Tesseract OCR on PATH: choco install tesseract"
        )
    work = _preprocess_for_ocr(image) if preprocess else image
    try:
        text = pytesseract.image_to_string(work)
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract executable not found on PATH.\n"
            "Install Tesseract: choco install tesseract\n"
            "Or download from: https://github.com/UB-Mannheim/tesseract/wiki"
        )
    except Exception as e:
        raise RuntimeError(f"OCR failed: {e}")
    return (text or "").strip()


def scan_and_extract(monitor_id: int, preprocess: bool = True) -> str:
    img = capture_screen(monitor_id)
    return extract_text(img, preprocess=preprocess)


def get_screen_context(monitor_id: int, preprocess: bool = True) -> Dict[str, Any]:
    """Capture screen and gather active window and app context."""
    text = scan_and_extract(monitor_id, preprocess=preprocess)
    active_title = get_active_window_title()
    meeting_app = detect_meeting_app()
    return {
        "ocr_text": text,
        "active_window": active_title,
        "meeting_app": meeting_app,
    }


class ScreenScanWorker(QThread):
    finished_ok = pyqtSignal(str)
    finished_details = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, monitor_id: int, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._monitor_id = monitor_id

    def run(self) -> None:
        try:
            active_title = get_active_window_title()
            meeting_app = detect_meeting_app()
            text = scan_and_extract(self._monitor_id)
            
            # Enrich text with active window context if available
            combined = text
            if active_title and "ghostmind" not in active_title.lower():
                header = f"[Active Window: {active_title}]"
                if meeting_app:
                    header += f" [Meeting App: {meeting_app}]"
                combined = f"{header}\n\n{text}" if text else header

            self.finished_details.emit({
                "ocr_text": text,
                "active_window": active_title,
                "meeting_app": meeting_app,
                "combined_text": combined,
            })
            self.finished_ok.emit(combined)
        except Exception as e:
            logger.exception("Screen scan failed")
            self.failed.emit(str(e))
