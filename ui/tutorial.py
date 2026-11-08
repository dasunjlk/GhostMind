"""Guided first-run tutorial: a coach-mark tour inside the overlay (C14).

Per step, four translucent "shade" widgets surround the target's mapped
geometry — they dim the app and swallow every click. The hole itself has no
widget, so the real control keeps hover/press behavior and receives genuine
clicks; a mouse-transparent ring only paints the green outline. The banner
floats above the shades and owns navigation.

Skip rules (2026-11-08 decision): the first run cannot be skipped — no Skip
link and Esc is inert — because programmatic Next guarantees every step is
reachable, so the tour can never dead-end. Replay runs (2nd+ via
Settings → About) show Skip and Esc skips.

Click modes per target:
- "passthrough": the widget receives the real click (e.g. the gear opens
  Settings) and the tour advances afterwards.
- "block": the click is swallowed (never trigger a scan, an API call, or
  click-through mid-tour) and the tour advances.
- "none": no event filter — the user explores the control freely and
  presses Next when done.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

_SHADE_STYLE = "background: rgba(0, 0, 0, 0.55);"
_RING_STYLE = "border: 2px solid #00FF88; border-radius: 6px; background: transparent;"
_BANNER_WIDTH = 330
_BANNER_MARGIN = 8
_TARGET_PAD = 5


@dataclass(frozen=True)
class TutorialStep:
    """One tour stop: copy, an optional target widget, and how it behaves."""

    title: str
    body: str
    target: Optional[Callable[[], Optional[QWidget]]] = None
    navigate: Optional[Callable[[], None]] = None
    click_mode: str = "none"  # "passthrough" | "block" | "none"


class _Shade(QWidget):
    """A blocking dim patch: accepts mouse events so they never reach the
    overlay's resize/drag handlers beneath."""

    def mousePressEvent(self, e) -> None:
        e.accept()

    def mouseReleaseEvent(self, e) -> None:
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        e.accept()

    def mouseDoubleClickEvent(self, e) -> None:
        e.accept()


class TutorialBanner(QFrame):
    """Dark green-bordered tour banner: title, body, counter, and buttons."""

    next_clicked = pyqtSignal()
    back_clicked = pyqtSignal()
    skip_clicked = pyqtSignal()
    done_clicked = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("tutorialBanner")
        self.setStyleSheet(
            "#tutorialBanner { background:#0F1712; border:1.5px solid #00FF88;"
            "border-radius:10px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        self._title = QLabel("")
        self._title.setWordWrap(True)
        self._title.setStyleSheet("color:#00FF88;font-size:13px;font-weight:bold;")
        layout.addWidget(self._title)

        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setStyleSheet("color:#E0E0E0;font-size:12px;line-height:1.45;")
        layout.addWidget(self._body)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self._counter = QLabel("")
        self._counter.setStyleSheet("color:#888888;font-size:11px;")
        foot.addWidget(self._counter)
        foot.addStretch(1)

        self._back_btn = QPushButton("Back")
        self._next_btn = QPushButton("Next")
        self._done_btn = QPushButton("Done")
        self._skip_btn = QPushButton("Skip tutorial")
        for btn, is_primary in (
            (self._back_btn, False),
            (self._next_btn, True),
            (self._done_btn, True),
        ):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:#00FF88;color:#0A0A0A;border:none;"
                "padding:5px 14px;font-weight:bold;border-radius:4px;font-size:11.5px;}"
                "QPushButton:hover{background:#33FFAA;}"
                if is_primary
                else "QPushButton{background:#1A1A1A;color:#CCCCCC;border:1px solid #333;"
                "padding:5px 12px;border-radius:4px;font-size:11.5px;}"
                "QPushButton:hover{background:#252525;}"
            )
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#888888;"
            "font-size:11px;text-decoration:underline;}"
            "QPushButton:hover{color:#CCCCCC;}"
        )
        self._next_btn.clicked.connect(self.next_clicked.emit)
        self._back_btn.clicked.connect(self.back_clicked.emit)
        self._done_btn.clicked.connect(self.done_clicked.emit)
        self._skip_btn.clicked.connect(self.skip_clicked.emit)
        foot.addWidget(self._back_btn)
        foot.addWidget(self._next_btn)
        foot.addWidget(self._done_btn)
        foot.addWidget(self._skip_btn)
        layout.addLayout(foot)

    def set_step(
        self,
        index: int,
        total: int,
        title: str,
        body: str,
        *,
        is_first: bool,
        is_last: bool,
        skippable: bool,
    ) -> None:
        self._title.setText(title)
        self._body.setText(body)
        self._counter.setText(f"Step {index} of {total}")
        self._back_btn.setVisible(not is_first)
        self._next_btn.setVisible(not is_last)
        self._done_btn.setVisible(is_last)
        # Skip only exists on replay runs, and the last banner ends via Done.
        self._skip_btn.setVisible(skippable and not is_last)
        self.adjustSize()
        self.setFixedWidth(_BANNER_WIDTH)


class TutorialController(QObject):
    """Drives the tour: shades + ring + banner over the live overlay."""

    finished = pyqtSignal(bool)  # True when the user reached the last step

    def __init__(
        self,
        overlay: QWidget,
        steps: List[TutorialStep],
        replay: bool,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._overlay = overlay
        self._steps = steps
        self._replay = replay
        self._index = 0
        self._active = False
        self._shades: List[QWidget] = []
        self._ring: Optional[QWidget] = None
        self._banner: Optional[TutorialBanner] = None
        self._target: Optional[QWidget] = None

    # ------------------------------------------------------------- public --

    @property
    def active(self) -> bool:
        return self._active

    @property
    def index(self) -> int:
        return self._index

    def start(self) -> None:
        if self._active:
            return
        # Same guard as open_settings: never tour through a click-through.
        if self._overlay._click_through_enabled():
            self._overlay.set_click_through(False)
            self._overlay.click_through_changed.emit(False)
        banner = TutorialBanner(self._overlay)
        banner.next_clicked.connect(self._next)
        banner.back_clicked.connect(self._back)
        banner.done_clicked.connect(lambda: self._finish(True))
        banner.skip_clicked.connect(lambda: self._finish(False))
        self._banner = banner
        self._active = True
        self._show_step(0)

    def skip(self) -> None:
        self._finish(False)

    def reposition(self) -> None:
        """Re-map the spotlight after the overlay moves or resizes."""
        if self._active:
            self._show_step(self._index)

    def handle_escape(self) -> bool:
        """Consume Esc during the tour. First run: inert (stay). Replay: skip.

        Returns True when Esc was consumed (the overlay must not minimize).
        """
        if not self._active:
            return False
        if self._replay:
            self._finish(False)
        return True

    # ------------------------------------------------------------ internal --

    def _show_step(self, index: int) -> None:
        self._index = index
        step = self._steps[index]
        if step.navigate is not None:
            step.navigate()

        self._clear_spotlight()
        self._detach_filter()

        win_w = self._overlay.width()
        win_h = self._overlay.height()
        target = step.target() if step.target is not None else None

        if target is not None:
            rect = self._mapped_rect(target)
            if rect is not None:
                self._build_spotlight(rect, win_w, win_h)
                self._target = target
                if step.click_mode in ("passthrough", "block"):
                    target.installEventFilter(self)
            else:
                self._target = None
        else:
            self._target = None

        if self._banner is None:
            return
        banner = self._banner
        banner.set_step(
            index + 1,
            len(self._steps),
            step.title,
            step.body,
            is_first=(index == 0),
            is_last=(index == len(self._steps) - 1),
            skippable=self._replay,
        )
        self._place_banner(target if self._target is not None else None, win_w, win_h)
        banner.show()
        banner.raise_()

    def _mapped_rect(self, target: QWidget) -> Optional[tuple]:
        try:
            top_left = target.mapTo(self._overlay, target.rect().topLeft())
        except RuntimeError:
            return None
        left = top_left.x() - _TARGET_PAD
        top = top_left.y() - _TARGET_PAD
        width = target.width() + _TARGET_PAD * 2
        height = target.height() + _TARGET_PAD * 2
        if width < 34:
            left -= int((34 - width) / 2)
            width = 34
        if height < 30:
            top -= int((30 - height) / 2)
            height = 30
        return (left, top, width, height)

    def _build_spotlight(self, rect: tuple, win_w: int, win_h: int) -> None:
        left, top, width, height = rect
        specs = [
            (0, 0, win_w, top),
            (0, top + height, win_w, max(0, win_h - top - height)),
            (0, top, max(0, left), height),
            (left + width, top, max(0, win_w - left - width), height),
        ]
        for x, y, w, h in specs:
            if w <= 0 or h <= 0:
                continue
            shade = _Shade(self._overlay)
            shade.setStyleSheet(_SHADE_STYLE)
            shade.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            shade.setGeometry(x, y, w, h)
            shade.show()
            shade.raise_()
            self._shades.append(shade)
        ring = QWidget(self._overlay)
        ring.setStyleSheet(_RING_STYLE)
        ring.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Visual only — the real widget beneath must receive the clicks.
        ring.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        ring.setGeometry(left, top, width, height)
        ring.show()
        ring.raise_()
        self._ring = ring

    def _place_banner(
        self, target: Optional[QWidget], win_w: int, win_h: int
    ) -> None:
        banner = self._banner
        if banner is None:
            return
        bh = banner.height()
        if target is not None and self._target is not None:
            rect = self._mapped_rect(self._target)
            if rect is not None:
                left, top, width, height = rect
                b_left = left + width // 2 - _BANNER_WIDTH // 2
                b_left = max(_BANNER_MARGIN, min(b_left, win_w - _BANNER_WIDTH - _BANNER_MARGIN))
                if top + height + 10 + bh < win_h - _BANNER_MARGIN:
                    b_top = top + height + 10
                else:
                    b_top = max(_BANNER_MARGIN, top - bh - 10)
                banner.move(b_left, b_top)
                return
        banner.move(
            max(_BANNER_MARGIN, (win_w - _BANNER_WIDTH) // 2),
            max(_BANNER_MARGIN, (win_h - bh) // 2),
        )

    def _clear_spotlight(self) -> None:
        for shade in self._shades:
            shade.hide()
            shade.deleteLater()
        self._shades = []
        if self._ring is not None:
            self._ring.hide()
            self._ring.deleteLater()
            self._ring = None

    def _detach_filter(self) -> None:
        if self._target is not None:
            try:
                self._target.removeEventFilter(self)
            except RuntimeError:
                pass
        self._target = None

    def _next(self) -> None:
        if not self._active:
            return
        if self._index >= len(self._steps) - 1:
            self._finish(True)
            return
        self._show_step(self._index + 1)

    def _back(self) -> None:
        if self._active and self._index > 0:
            self._show_step(self._index - 1)

    def _finish(self, completed: bool) -> None:
        if not self._active:
            return
        self._active = False
        self._detach_filter()
        self._clear_spotlight()
        if self._banner is not None:
            self._banner.hide()
            self._banner.deleteLater()
            self._banner = None
        self.finished.emit(completed)

    # ------------------------------------------------------ event filter --

    def eventFilter(self, obj: QObject, event) -> bool:
        if obj is self._target and self._active:
            et = event.type()
            mode = self._steps[self._index].click_mode
            if mode == "block":
                if et == event.Type.MouseButtonPress:
                    # Swallow the click (no scan / no API call mid-tour) and move on.
                    QTimer.singleShot(0, self._next)
                    return True
                if et == event.Type.MouseButtonRelease:
                    return True
            elif mode == "passthrough":
                if et == event.Type.MouseButtonRelease:
                    # Let the widget handle the real click, then advance.
                    QTimer.singleShot(0, self._next)
        return super().eventFilter(obj, event)


def build_steps(overlay: QWidget, panel) -> List[TutorialStep]:
    """The 16-step script, bound to the live overlay and settings panel."""

    def general() -> None:
        overlay.open_settings()
        panel.focus_tab("general")

    def shortcuts() -> None:
        overlay.open_settings()
        panel.focus_tab("keys")

    def api() -> None:
        overlay.open_settings()
        panel.focus_tab("api")

    def prefs() -> None:
        overlay.open_settings()
        panel.focus_tab("prefs")

    def about() -> None:
        overlay.open_settings()
        panel.focus_tab("about")

    def home() -> None:
        overlay.show_main_page()

    return [
        TutorialStep(
            "Welcome to GhostMind 👋",
            "This quick tour shows you around — it takes under a minute. "
            "Click the ⚙ gear to open Settings.",
            target=lambda: overlay._btn_set,
            click_mode="passthrough",
        ),
        TutorialStep(
            "Pick your screen",
            "Which monitor should GhostMind scan? Most people leave this "
            "on Monitor 1.",
            navigate=general,
            target=lambda: panel._monitor,
        ),
        TutorialStep(
            "Scan mode",
            "Manual scans when you press ⚡ or Ctrl+Shift+S. Auto rescans "
            "every few seconds — hands-free.",
            navigate=general,
            target=lambda: panel._scan_mode,
        ),
        TutorialStep(
            "Window opacity",
            "Slide to make the overlay more transparent or more solid.",
            navigate=general,
            target=lambda: panel._opacity,
        ),
        TutorialStep(
            "Click-through",
            "When ON, clicks pass through the overlay so it never blocks "
            "what is underneath. Ctrl+Shift+X turns it off anytime.",
            navigate=general,
            target=lambda: panel._click_through,
        ),
        TutorialStep(
            "Save your changes",
            "Save applies everything in Settings. Import / Export move "
            "your setup between machines.",
            navigate=general,
            target=lambda: panel._save_btn,
            click_mode="block",
        ),
        TutorialStep(
            "Global hotkeys",
            "Seven shortcuts work from anywhere in Windows — retype any "
            "of them, then press Save.",
            navigate=shortcuts,
            target=lambda: panel._keys_tab,
        ),
        TutorialStep(
            "Connect your AI — the important one",
            "Groq works out of the box with this Base URL. OpenRouter and "
            "other compatible providers just need a different address here.",
            navigate=api,
            target=lambda: panel._api_base_url,
        ),
        TutorialStep(
            "Paste your API key",
            "Grab a free key at console.groq.com and paste it here. It "
            "never leaves your device except to talk to the provider.",
            navigate=api,
            target=lambda: panel._api_key,
        ),
        TutorialStep(
            "Choose your model",
            "The AI brain that answers you. Every provider names its "
            "models differently — pick one from the list, or type any "
            "model ID your provider supports.",
            navigate=api,
            target=lambda: panel._ai_model,
        ),
        TutorialStep(
            "Check Available Model",
            "One click verifies your Base URL and key, then shows every "
            "model this key can use.",
            navigate=api,
            target=lambda: panel._check_btn,
            click_mode="block",
        ),
        TutorialStep(
            "Your key stays safe",
            "Save stores the key in Windows Credential Manager — never "
            "in a plain file.",
            navigate=api,
            target=lambda: panel._save_btn,
            click_mode="block",
        ),
        TutorialStep(
            "Make it readable",
            "Font size for answers, subtitles, and the whole app — 9 to "
            "24 pt.",
            navigate=prefs,
            target=lambda: panel._font_size,
        ),
        TutorialStep(
            "About GhostMind",
            "Version info and the GitHub page — and Replay tutorial "
            "lives right here whenever you want this tour again.",
            navigate=about,
            target=lambda: panel._about_tab,
        ),
        TutorialStep(
            "Scan your screen ⚡",
            "Press ⚡ (or Ctrl+Shift+S): GhostMind reads the screen and "
            "answers what it finds.",
            navigate=home,
            target=lambda: overlay._btn_scan,
            click_mode="block",
        ),
        TutorialStep(
            "Pointer mode",
            "This toggle lets clicks pass through the overlay — handy "
            "when you only want to look.",
            target=lambda: overlay._click_through_toggle,
            click_mode="block",
        ),
        TutorialStep(
            "Just ask",
            "Type any question at the bottom and press Enter — no "
            "scanning needed.",
            target=lambda: overlay._ask_input,
            click_mode="passthrough",
        ),
        TutorialStep(
            "You're ready 🎉",
            "⚡ Scan something, or type a question below. Enjoy! (Replay "
            "this tour anytime: Settings → About.)",
        ),
    ]
