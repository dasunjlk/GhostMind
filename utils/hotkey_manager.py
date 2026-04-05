"""
Global hotkeys via the `keyboard` library; emits Qt signals on the main thread.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

try:
    import keyboard
except ImportError:  # pragma: no cover
    keyboard = None  # type: ignore


class HotkeyManager(QObject):
    toggle_visibility = pyqtSignal()
    trigger_screen_scan = pyqtSignal()
    clear_answers = pyqtSignal()
    toggle_subtitles = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._handles: List[Callable[[], None]] = []
        self._registered: Dict[str, Callable[[], None]] = {}

    def update_hotkeys(
        self,
        toggle_vis: str,
        scan: str,
        clear: str,
        toggle_sub: str,
    ) -> None:
        self.unregister_all()
        if keyboard is None:
            logger.warning("keyboard library not available; global hotkeys disabled")
            return

        mapping = {
            toggle_vis: self.toggle_visibility.emit,
            scan: self.trigger_screen_scan.emit,
            clear: self.clear_answers.emit,
            toggle_sub: self.toggle_subtitles.emit,
        }

        for combo, emitter in mapping.items():
            combo = (combo or "").strip()
            if not combo:
                continue

            def _make_emit(fn: Callable[[], None]) -> Callable[[], None]:
                def _wrapped() -> None:
                    try:
                        fn()
                    except Exception as e:  # pragma: no cover
                        logger.error("hotkey emit failed: %s", e)

                return _wrapped

            try:
                h = keyboard.add_hotkey(combo, _make_emit(emitter), suppress=False)
                self._handles.append(h)
                self._registered[combo] = emitter
            except Exception as e:
                logger.error("Failed to register hotkey %r: %s", combo, e)

    def unregister_all(self) -> None:
        if keyboard is None:
            self._handles.clear()
            self._registered.clear()
            return
        for h in self._handles:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self._handles.clear()
        self._registered.clear()
