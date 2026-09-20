"""
Main frameless always-on-top overlay: tabs, custom resize, header drag, stealth hooks.
"""
from __future__ import annotations

from enum import IntFlag, auto
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    QEvent,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.ai_engine import AiStreamWorker, DEFAULT_MODEL
from core.screen_reader import ScreenScanWorker
from core.stealth import apply_stealth

from ui.answer_panel import AnswerPanel
from ui.settings_panel import SettingsPanel
from ui.subtitle_bar import SubtitleBar


class Edge(IntFlag):
    NONE = 0
    LEFT = auto()
    RIGHT = auto()
    TOP = auto()
    BOTTOM = auto()


FRAME = 8


def _load_fonts(repo_root: Path) -> None:
    font_dir = repo_root / "assets" / "fonts"
    if not font_dir.is_dir():
        return
    for p in font_dir.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(p))
    for p in font_dir.glob("*.otf"):
        QFontDatabase.addApplicationFont(str(p))


class _HeaderDragFilter(QObject):
    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._drag: Optional[QPoint] = None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            me = event
            assert isinstance(me, QMouseEvent)
            if me.button() == Qt.MouseButton.LeftButton:
                self._drag = me.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
                return False
        if event.type() == QEvent.Type.MouseMove:
            me = event
            assert isinstance(me, QMouseEvent)
            if self._drag is not None and me.buttons() & Qt.MouseButton.LeftButton:
                self._window.move(me.globalPosition().toPoint() - self._drag)
                return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._drag = None
        return False


class _RoundCtl(QPushButton):
    def __init__(self, color: str, hover_color: str = "", parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedSize(12, 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        hover = hover_color or color
        self.setStyleSheet(
            f"QPushButton {{ background:{color}; border-radius:6px; border:none; }}"
            f"QPushButton:hover {{ background:{hover}; }}"
        )


class _CaptureIconWidget(QWidget):
    """Zoom-style capture toggle: drawn mic/speaker glyph, red slash when off.

    Click toggles; the app state lives in the capture settings that callers sync.
    """

    toggled = pyqtSignal(bool)

    def __init__(
        self,
        kind: str,
        enabled: bool,
        tooltip_base: str,
        has_device: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._on = bool(enabled)
        self._has_device = bool(has_device)
        self._tooltip_base = tooltip_base
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._tooltip_text())

    def set_has_device(self, has: bool) -> None:
        """Mark the hardware missing (mic icon shows an amber "!" badge)."""
        if self._has_device != bool(has):
            self._has_device = bool(has)
            self.update()
            self.setToolTip(self._tooltip_text())

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool) -> None:
        if self._on != bool(on):
            self._on = bool(on)
            self.update()
            self.setToolTip(self._tooltip_text())

    def _tooltip_text(self) -> str:
        if self._kind == "mic" and not self._has_device:
            return f"{self._tooltip_base} — no microphone detected on this system"
        return f"{self._tooltip_base} — {'on' if self._on else 'off'} (click to toggle)"

    def mousePressEvent(self, a0) -> None:  # noqa: N802 (Qt naming)
        self._on = not self._on
        self.update()
        self.setToolTip(self._tooltip_text())
        self.toggled.emit(self._on)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        if self.underMouse():
            p.fillRect(r, QColor(34, 34, 34))

        color = QColor("#00FF88") if self._on else QColor("#888888")
        cx = r.center().x()
        right_edge = r.right()
        bottom_edge = r.bottom()

        if self._kind == "mic":
            # Capsule + arc + stand, from a 7x13 cell centered in the widget
            w, h = 7.0, 13.0
            x = cx - w / 2.0
            y = (r.height() - h) / 2.0 - 1.5
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, y, w, h), 3.5, 3.5)
            p.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(color)
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.drawArc(QRectF(x - 3.5, y + 2.0, w + 7.0, h + 2.0), -60 * 16, 120 * 16 - 1)
            p.drawLine(QPointF(cx, y + h + 0.5), QPointF(cx, bottom_edge - 3.0))
            p.drawLine(QPointF(cx - 3.0, bottom_edge - 3.0), QPointF(cx + 3.0, bottom_edge - 3.0))
        else:  # "speaker"
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            box_w, box_h = 6.0, 8.0
            bx = cx - 6.5 - box_w / 2.0
            by = (r.height() - box_h) / 2.0
            p.drawPolygon(
                QPolygonF(
                    [
                        QPointF(bx, by),
                        QPointF(bx + box_w, by - 1.5),
                        QPointF(bx + box_w, by + box_h + 1.5),
                        QPointF(bx, by + box_h),
                    ]
                )
            )
            p.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(color)
            pen.setWidthF(1.7)
            p.setPen(pen)
            for ax in (bx + box_w, bx + box_w + 3.0):
                p.drawArc(QRectF(ax, r.height() / 2.0 - 5.5, 5.0, 11.0), -55 * 16, 110 * 16 - 1)

        if self._kind == "mic" and not self._has_device:
            # Zoom-style amber "!" badge: no input hardware on this system
            pen = QPen(QColor(255, 193, 7), 2.0)
            p.setPen(pen)
            p.drawLine(QPointF(r.right() - 9.5, r.top() + 5.0), QPointF(r.right() - 9.5, r.top() + 11.0))
            p.drawPoint(QPointF(r.right() - 9.5, r.top() + 13.5))

        if not self._on:
            # Zoom-style red slash over the glyph
            pen = QPen(QColor(255, 68, 68), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(r.left() + 4, r.top() + 4), QPointF(right_edge - 4, bottom_edge - 4))


def _is_worker_active(worker: Optional[QThread]) -> bool:
    """Safely check if a QThread worker is alive without triggering C++ deleted object errors."""
    if worker is None:
        return False
    try:
        from PyQt6 import sip
        if sip.isdeleted(worker):
            return False
        return bool(worker.isRunning())
    except (RuntimeError, ReferenceError, TypeError):
        # TypeError: a non-sip object was passed (defensive; should not happen)
        return False



class OverlayWindow(QMainWindow):
    settings_changed = pyqtSignal(dict)
    geometry_changed = pyqtSignal(dict)
    closeRequested = pyqtSignal()
    export_requested = pyqtSignal()
    summarize_meeting_requested = pyqtSignal()

    def __init__(self, settings: Dict[str, Any], repo_root: Path, parent=None) -> None:
        super().__init__(parent)
        self._repo_root = repo_root
        self._settings = dict(settings)
        self._resize_edge = Edge.NONE
        self._resize_start_pos: Optional[QPoint] = None
        self._resize_start_geom: Optional[QRect] = None
        self._ai_worker: Optional[AiStreamWorker] = None
        self._scan_worker: Optional[ScreenScanWorker] = None
        self._visible_target = True
        self.close_event_allowed = True
        self._opacity_anim: Optional[QVariantAnimation] = None
        self._restoring_geometry = False
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._emit_geometry)

        _load_fonts(repo_root)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(480, 600)
        self.setMinimumSize(320, 360)
        self._restore_window_geometry()

        ico_path = self._repo_root / "assets" / "icon.ico"
        if ico_path.is_file():
            self.setWindowIcon(QIcon(str(ico_path)))

        # Outer transparent container with 2px inset margin to prevent DWM border bleed
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(2, 2, 2, 2)
        c_layout.setSpacing(0)

        central = QWidget()
        central.setObjectName("ghostPanel")
        central.setStyleSheet(
            "#ghostPanel { background: rgba(10,10,10,225); border: 1px solid #00FF88; "
            "border-radius: 8px; }"
        )
        c_layout.addWidget(central)
        self.setCentralWidget(container)

        root = QVBoxLayout(central)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # Header Bar
        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet("background:#141414; border-top-left-radius:7px; border-top-right-radius:7px;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 8, 0)

        title = QLabel(" GhostMind")
        title.setStyleSheet("color:#00FF88; font-weight: bold;")
        _families = QFontDatabase.families()
        ui_font = QFont("Inter", 11)
        if "Inter" in _families:
            pass
        elif "DM Sans" in _families:
            ui_font = QFont("DM Sans", 11)
        else:
            ui_font = QFont("Segoe UI", 11)
        title.setFont(ui_font)

        btn_close = _RoundCtl("#FF4444", "#FF6B6B")
        btn_close.setToolTip("Hide to Tray")
        btn_close.clicked.connect(self.close)

        btn_min = _RoundCtl("#FFD54F", "#FFE082")
        btn_min.setToolTip("Minimize")
        btn_min.clicked.connect(self._minimize_hide)


        # Scan button: same action as the screen-scan hotkey (Ctrl+Shift+S)
        btn_scan = QPushButton("⚡ Scan")
        btn_scan.setObjectName("scanBtn")
        btn_scan.setToolTip("Scan screen & answer (Ctrl+Shift+S)")
        btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_scan.setStyleSheet(
            "#scanBtn { background: transparent; color: #00FF88; border: 1px solid #00FF88;"
            " border-radius: 4px; padding: 2px 10px; font-size: 12px; font-weight: bold; }"
            "#scanBtn:hover { background: rgba(0, 255, 136, 0.15); }"
            "#scanBtn:pressed { background: rgba(0, 255, 136, 0.30); }"
            "#scanBtn:disabled { color: #556; border-color: #556; }"
        )
        btn_scan.clicked.connect(self.trigger_screen_scan)
        self._btn_scan = btn_scan

        # Settings Gear Icon Button
        btn_set = QPushButton("⚙")
        btn_set.setToolTip("Settings")
        btn_set.setFixedSize(26, 26)
        btn_set.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_set.setStyleSheet(
            "QPushButton { background: transparent; color: #888888; border: none; font-size: 15px; border-radius: 4px; padding-bottom: 2px; }"
            "QPushButton:hover { background: #222222; color: #00FF88; }"
        )
        btn_set.clicked.connect(self._toggle_settings)

        # Quick capture toggles (Zoom-style): click to enable/disable mic / system
        # audio. Kept in sync with the Audio tab via settings_changed/apply_settings.
        self._mic_toggle = _CaptureIconWidget(
            "mic", bool(self._settings.get("capture_mic", True)), "Microphone capture"
        )
        self._mic_toggle.toggled.connect(self._on_quick_capture_toggle)
        self._sys_toggle = _CaptureIconWidget(
            "speaker",
            bool(self._settings.get("capture_system", True)),
            "System audio capture",
        )
        self._sys_toggle.toggled.connect(self._on_quick_capture_toggle)
        # main.py probes audio hardware and calls set_microphone_available().
        self._has_microphone: Optional[bool] = None

        hl.addWidget(btn_close)
        hl.addWidget(btn_min)
        hl.addSpacing(8)
        hl.addWidget(title)
        hl.addStretch(1)
        hl.addWidget(btn_scan)
        hl.addSpacing(6)
        hl.addWidget(self._mic_toggle)
        hl.addSpacing(2)
        hl.addWidget(self._sys_toggle)
        hl.addSpacing(4)
        hl.addWidget(btn_set)

        root.addWidget(header)

        self._stack = QStackedWidget()
        self._main_page = QWidget()
        mp_lay = QVBoxLayout(self._main_page)
        mp_lay.setContentsMargins(6, 6, 6, 6)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: none; background: transparent; }"
            "QTabBar::tab { color:#888; padding:6px 14px; background: transparent; border:none; }"
            "QTabBar::tab:selected { color:#00FF88; border-bottom:2px solid #00FF88; }"
            "QTabBar::tab:hover { color:#E0E0E0; }"
        )

        self._answer_panel = AnswerPanel()
        self._subtitle_bar = SubtitleBar()
        sub_host = QWidget()
        sl = QVBoxLayout(sub_host)
        sl.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("Live transcription (Mic / System / Lecturer). Questions highlighted in gold.")
        hint.setStyleSheet("color:#888;font-size:11px;")
        sl.addWidget(hint)
        sl.addWidget(self._subtitle_bar, 1)

        self._tabs.addTab(self._answer_panel, "Answers")
        self._tabs.addTab(sub_host, "Subtitles")
        mp_lay.addWidget(self._tabs, 1)

        # --- Manual question input (F-01) ---
        self._ask_row = QWidget()
        ask_lay = QHBoxLayout(self._ask_row)
        ask_lay.setContentsMargins(6, 0, 6, 6)
        ask_lay.setSpacing(6)
        self._ask_input = QLineEdit()
        self._ask_input.setPlaceholderText("Ask anything… (Enter to send, Shift+Enter for new line)")
        self._ask_input.setStyleSheet(
            "QLineEdit { background:#141414; color:#E0E0E0; border:1px solid #333;"
            " border-radius:4px; padding:4px 8px; font-size:12px; }"
            "QLineEdit:focus { border-color:#00FF88; }"
        )
        self._ask_input.returnPressed.connect(self._send_manual_question)
        self._ask_btn = QPushButton("Ask")
        self._ask_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ask_btn.setStyleSheet(
            "QPushButton { background:#162B1E; color:#00FF88; border:1px solid #00FF88;"
            " padding:4px 12px; border-radius:4px; font-size:12px; font-weight:bold; }"
            "QPushButton:hover { background:#1E3E2B; }"
            "QPushButton:disabled { color:#556; border-color:#556; }"
        )
        self._ask_btn.clicked.connect(self._send_manual_question)
        ask_lay.addWidget(self._ask_input, 1)
        ask_lay.addWidget(self._ask_btn)
        mp_lay.addWidget(self._ask_row)

        self._settings_panel = SettingsPanel(self._settings)
        self._settings_panel.hide()
        self._settings_panel.saved.connect(self._on_settings_saved)
        self._settings_panel.opacity_preview.connect(self._apply_window_opacity)

        self._subtitle_bar.save_requested.connect(self.export_requested.emit)
        self._subtitle_bar.summarize_requested.connect(self.summarize_meeting_requested.emit)

        self._stack.addWidget(self._main_page)
        self._stack.addWidget(self._settings_panel)
        root.addWidget(self._stack, 1)

        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._trigger_scan)

        self._apply_window_opacity(float(self._settings.get("opacity", 0.92)))
        self.apply_font_size(int(self._settings.get("font_size", 13)))

        self._header_drag = _HeaderDragFilter(self)
        header.installEventFilter(self._header_drag)

        self._apply_auto_timer_state()

    # --- public API for main.py ---
    def apply_settings(self, s: Dict[str, Any]) -> None:
        self._settings.update(s)
        self._apply_window_opacity(float(self._settings.get("opacity", 0.92)))
        self._apply_auto_timer_state()
        self._settings_panel.apply_data(self._settings)
        self._mic_toggle.set_on(bool(self._settings.get("capture_mic", True)))
        self._sys_toggle.set_on(bool(self._settings.get("capture_system", True)))
        self.apply_font_size(int(self._settings.get("font_size", 13)))
        self._reapply_stealth()

    def apply_font_size(self, pt: int) -> None:
        """Apply the user's font size preference across the app (Preferences)."""
        pt = max(9, min(24, int(pt)))
        f = self.font()
        f.setPointSize(pt)
        self.setFont(f)  # cascades to headers, tabs, buttons, settings panel
        self._answer_panel.apply_font_size(pt)
        self._subtitle_bar.apply_font_size(pt)
        self._ask_input.setStyleSheet(
            f"QLineEdit {{ background:#141414; color:#E0E0E0; border:1px solid #333;"
            f" border-radius:4px; padding:4px 8px; font-size:{pt}px; }}"
            f"QLineEdit:focus {{ border-color:#00FF88; }}"
        )

    def _on_quick_capture_toggle(self, _on: bool) -> None:
        """Header mic/speaker icons changed: persist + restart audio capture."""
        self._settings["capture_mic"] = self._mic_toggle.is_on()
        self._settings["capture_system"] = self._sys_toggle.is_on()
        self.settings_changed.emit(dict(self._settings))

    def set_microphone_available(self, available: bool) -> None:
        """Show an amber "!" on the mic icon when the system has no input device."""
        self._has_microphone = bool(available)
        self._mic_toggle.set_has_device(bool(available))

    def push_subtitle_line(self, line: str) -> None:
        self._subtitle_bar.append_line(line)

    def toggle_visibility_animated(self) -> None:
        self._visible_target = not self._visible_target
        if self._visible_target:
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
            self._fade_to(float(self._settings.get("opacity", 0.92)))
        else:
            self._fade_to(0.0, hide_on_finish=True)

    def request_ai_answer(self, content: str, context_type: str = "screen") -> None:
        """Run Groq on arbitrary text (e.g. meeting question or transcript)."""
        if not (content or "").strip():
            return
        self._tabs.setCurrentIndex(0)
        self._start_ai(content.strip(), context_type)

    def focus_question_input(self) -> None:
        """Hotkey target (Ctrl+Shift+Q): surface the overlay and focus the Ask box."""
        if self._stack.currentIndex() == 1:
            self._stack.setCurrentIndex(0)
            self._settings_panel.hide()
        self._tabs.setCurrentIndex(0)
        if not self.isVisible():
            self.toggle_visibility_animated()
        self.raise_()
        self._ask_input.setFocus()

    def _send_manual_question(self) -> None:
        """Ask button / Enter in the manual question box (F-01)."""
        text = self._ask_input.text().strip()
        if not text:
            return
        if _is_worker_active(self._ai_worker):
            # Send rejected: keep the typed text so nothing is lost.
            self._answer_panel.end_stream_error("Already processing another answer.")
            return
        self._ask_input.clear()  # accepted: free the box for the next question
        # Chat-style: echo the user's message in the panel. Scan/OCR answers do
        # not get this bubble — only typed messages do (F-01).
        self._answer_panel.add_user_message(text)
        self.request_ai_answer(text, "manual")

    def trigger_screen_scan(self) -> None:
        if _is_worker_active(self._scan_worker):
            return
        mid = int(self._settings.get("monitor_id", 1))
        self._tabs.setCurrentIndex(0)
        self._answer_panel.start_thinking()
        self._btn_scan.setEnabled(False)
        worker = ScreenScanWorker(mid)
        self._scan_worker = worker

        def _cleanup_scan() -> None:
            if self._scan_worker is worker:
                self._scan_worker = None
            self._btn_scan.setEnabled(True)

        worker.finished.connect(_cleanup_scan)
        worker.finished.connect(worker.deleteLater)
        worker.finished_ok.connect(self._on_scan_done)
        worker.failed.connect(self._on_scan_fail)
        worker.start()

    def clear_answers(self) -> None:
        self._answer_panel.clear_all()

    def toggle_subtitles_tab(self) -> None:
        idx = 1 if self._tabs.currentIndex() == 0 else 0
        self._tabs.setCurrentIndex(idx)

    # --- internals ---
    def _minimize_hide(self) -> None:
        self._visible_target = False
        self._fade_to(0.0, hide_on_finish=True)

    def _toggle_settings(self) -> None:
        if self._stack.currentIndex() == 1:
            self._stack.setCurrentIndex(0)
            self._settings_panel.hide()
        else:
            self._settings_panel.apply_data(self._settings)
            self._stack.setCurrentIndex(1)
            self._settings_panel.show()

    def _on_settings_saved(self, data: Dict[str, Any]) -> None:
        self._settings.update(data)
        self.settings_changed.emit(dict(self._settings))
        self._stack.setCurrentIndex(0)
        self._settings_panel.hide()

    def _apply_auto_timer_state(self) -> None:
        if str(self._settings.get("scan_mode", "manual")) == "auto":
            sec = max(5, int(self._settings.get("auto_scan_interval_sec", 30)))
            self._auto_timer.start(sec * 1000)
        else:
            self._auto_timer.stop()

    def _trigger_scan(self) -> None:
        self.trigger_screen_scan()

    def _on_scan_done(self, text: str) -> None:
        if not text.strip():
            self._answer_panel.end_stream_error(
                "OCR returned no text. The screen may be blank or Tesseract could not read it."
            )
            return
        self._start_ai(text, "screen")

    def _on_scan_fail(self, err: str) -> None:
        msg = str(err)
        if "pytesseract" in msg.lower() or "tesseract" in msg.lower():
            friendly = (
                "Screen scan failed: Tesseract OCR is not available.\n\n"
                "Install Tesseract: choco install tesseract\n"
                "Then restart GhostMind."
            )
        elif "mss" in msg.lower():
            friendly = (
                "Screen capture failed. Check that the monitor ID is correct in Settings."
            )
        else:
            friendly = f"Screen scan error: {msg}"
        self._answer_panel.end_stream_error(friendly)

    def _start_ai(self, content: str, context_type: str) -> None:
        if _is_worker_active(self._ai_worker):
            if context_type == "meeting_audio":
                return
            self._answer_panel.stop_thinking()
            self._answer_panel.end_stream_error("Already processing another answer.")
            return

        model_id = str(self._settings.get("ai_model", DEFAULT_MODEL))

        self._answer_panel.begin_answer_stream()
        worker = AiStreamWorker(content, context_type, model_id=model_id)
        self._ai_worker = worker

        def _cleanup_ai() -> None:
            if self._ai_worker is worker:
                self._ai_worker = None

        worker.chunk_received.connect(self._answer_panel.append_stream_chunk)
        worker.finished_ok.connect(self._answer_panel.end_stream_success)
        worker.failed.connect(self._answer_panel.end_stream_error)
        worker.finished.connect(_cleanup_ai)
        worker.finished.connect(worker.deleteLater)
        worker.start()


    def _apply_window_opacity(self, op: float) -> None:
        op = max(0.20, min(1.0, float(op)))
        self.setWindowOpacity(op)

    def _fade_to(self, target: float, hide_on_finish: bool = False) -> None:
        anim = QVariantAnimation(self)
        anim.setDuration(150)
        anim.setStartValue(float(self.windowOpacity()))
        anim.setEndValue(float(target))
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))

        def _fin() -> None:
            self.setWindowOpacity(float(target))
            if hide_on_finish and target <= 0.01:
                self.hide()

        anim.finished.connect(_fin)
        anim.start()
        self._opacity_anim = anim

    def _reapply_stealth(self) -> None:
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        if hwnd:
            apply_stealth(
                hwnd,
                click_through=bool(self._settings.get("click_through", False)),
                dwm_cloak=bool(self._settings.get("dwm_cloak", False)),
            )

    def showEvent(self, e) -> None:
        super().showEvent(e)
        QTimer.singleShot(50, self._reapply_stealth)

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self._reapply_stealth()
        self._schedule_geometry_save()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._reapply_stealth()
        self._schedule_geometry_save()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self._flush_geometry_save()

    # --- window geometry persistence (R-04) ---
    def _restore_window_geometry(self) -> None:
        """Restore last saved size/position, clamped into available screen space."""
        self._restoring_geometry = True
        try:
            w = self._settings.get("window_w")
            h = self._settings.get("window_h")
            if isinstance(w, int) and isinstance(h, int) and w >= 320 and h >= 360:
                self.resize(w, h)
            x = self._settings.get("window_x")
            y = self._settings.get("window_y")
            if isinstance(x, int) and isinstance(y, int):
                self.move(self._clamped_position(QPoint(x, y)))
        finally:
            self._restoring_geometry = False

    def _clamped_position(self, pos: QPoint) -> QPoint:
        """Clamp a stored position into visible screen space.

        Handles a disconnected monitor gracefully: falls back to the stored
        screen name, then to the primary screen, so the window can never be
        restored stranded offscreen.
        """
        screen = QApplication.screenAt(pos)
        if screen is None:
            name = self._settings.get("window_screen")
            screen = next(
                (s for s in QApplication.screens() if s.name() == name), None
            ) or QApplication.primaryScreen()
        if screen is None:
            return pos
        avail = screen.availableGeometry()
        margin = 40
        x = max(avail.left() - self.width() + margin, min(pos.x(), avail.right() - margin))
        y = max(avail.top(), min(pos.y(), avail.bottom() - margin))
        return QPoint(x, y)

    def _schedule_geometry_save(self) -> None:
        """Debounce geometry persistence; skip during restore and fade animations."""
        if self._restoring_geometry:
            return
        if self._opacity_anim is not None and self._opacity_anim.state() == QAbstractAnimation.State.Running:
            return
        self._geometry_save_timer.start(500)

    def _flush_geometry_save(self) -> None:
        """Persist geometry immediately (e.g. when the window hides)."""
        self._geometry_save_timer.stop()
        if not self._restoring_geometry:
            self._emit_geometry()

    def _emit_geometry(self) -> None:
        g = self.geometry()
        screen = QApplication.screenAt(g.center())
        self.geometry_changed.emit(
            {
                "window_x": g.x(),
                "window_y": g.y(),
                "window_w": g.width(),
                "window_h": g.height(),
                "window_screen": screen.name() if screen else self._settings.get("window_screen"),
            }
        )

    def _edge_at(self, pos: QPoint) -> Edge:
        g = self.geometry()
        x, y = pos.x(), pos.y()
        e = Edge.NONE
        if x <= FRAME:
            e |= Edge.LEFT
        if x >= g.width() - FRAME:
            e |= Edge.RIGHT
        if y <= FRAME:
            e |= Edge.TOP
        if y >= g.height() - FRAME:
            e |= Edge.BOTTOM
        return e

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            edge = self._edge_at(e.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_start_pos = e.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._resize_edge != Edge.NONE and self._resize_start_pos and self._resize_start_geom:
            gp = e.globalPosition().toPoint()
            dx = gp.x() - self._resize_start_pos.x()
            dy = gp.y() - self._resize_start_pos.y()
            g = QRect(self._resize_start_geom)
            min_w, min_h = self.minimumWidth(), self.minimumHeight()
            if Edge.LEFT in self._resize_edge:
                new_w = g.width() - dx
                if new_w >= min_w:
                    g.setLeft(g.left() + dx)
            if Edge.RIGHT in self._resize_edge:
                new_w = g.width() + dx
                if new_w >= min_w:
                    g.setRight(g.right() + dx)
            if Edge.TOP in self._resize_edge:
                new_h = g.height() - dy
                if new_h >= min_h:
                    g.setTop(g.top() + dy)
            if Edge.BOTTOM in self._resize_edge:
                new_h = g.height() + dy
                if new_h >= min_h:
                    g.setBottom(g.bottom() + dy)
            self.setGeometry(g)
        else:
            edge = self._edge_at(e.position().toPoint())
            self._set_resize_cursor(edge)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._resize_edge = Edge.NONE
        self._resize_start_pos = None
        self._resize_start_geom = None
        super().mouseReleaseEvent(e)

    def _set_resize_cursor(self, edge: Edge) -> None:
        if edge == Edge.NONE:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return
        if edge == (Edge.LEFT | Edge.TOP) or edge == (Edge.RIGHT | Edge.BOTTOM):
            self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        elif edge == (Edge.RIGHT | Edge.TOP) or edge == (Edge.LEFT | Edge.BOTTOM):
            self.setCursor(QCursor(Qt.CursorShape.SizeBDiagCursor))
        elif edge == Edge.LEFT or edge == Edge.RIGHT:
            self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        elif edge == Edge.TOP or edge == Edge.BOTTOM:
            self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def closeEvent(self, e) -> None:
        """Intercept close: hide to tray unless close_event_allowed is True."""
        self._flush_geometry_save()
        if not self.close_event_allowed:
            e.ignore()
            self.closeRequested.emit()
        else:
            super().closeEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        """Handle keyboard navigation within the overlay."""
        key = e.key()
        if key == Qt.Key.Key_Escape:
            if self._stack.currentIndex() == 1:
                self._toggle_settings()
            else:
                self._minimize_hide()
            return
        if key == Qt.Key.Key_Tab:
            idx = self._tabs.currentIndex()
            self._tabs.setCurrentIndex((idx + 1) % self._tabs.count())
            return
        if key == Qt.Key.Key_Backtab:
            idx = self._tabs.currentIndex()
            self._tabs.setCurrentIndex((idx - 1) % self._tabs.count())
            return
        super().keyPressEvent(e)

    def leaveEvent(self, e) -> None:
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(e)
