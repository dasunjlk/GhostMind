"""
Multi-monitor capture (mss), OCR (pytesseract), optional OpenCV preprocessing.
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
        raise RuntimeError("pytesseract is not installed")
    work = _preprocess_for_ocr(image) if preprocess else image
    text = pytesseract.image_to_string(work)
    return (text or "").strip()


def scan_and_extract(monitor_id: int, preprocess: bool = True) -> str:
    img = capture_screen(monitor_id)
    return extract_text(img, preprocess=preprocess)


class ScreenScanWorker(QThread):
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, monitor_id: int, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._monitor_id = monitor_id

    def run(self) -> None:
        try:
            text = scan_and_extract(self._monitor_id)
            self.finished_ok.emit(text)
        except Exception as e:
            logger.exception("Screen scan failed")
            self.failed.emit(str(e))
