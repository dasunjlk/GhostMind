"""
Main frameless always-on-top overlay: tabs, custom resize, header drag, stealth hooks.
"""
from __future__ import annotations

from enum import IntFlag, auto
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QRect,
    Qt,
    QTimer,
    QVariantAnimation,
    QEvent,
    pyqtSignal,
)
from PyQt6.QtGui import QCursor, QFont, QFontDatabase, QIcon, QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.ai_engine import AiStreamWorker
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
    def __init__(self, color: str, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedSize(12, 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ background:{color}; border-radius:6px; border:none; }}"
            f"QPushButton:hover {{ background:{color}; filter: brightness(1.15); }}"
        )


class OverlayWindow(QMainWindow):
    settings_changed = pyqtSignal(dict)
    closeRequested = pyqtSignal()
    export_requested = pyqtSignal()

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

        _load_fonts(repo_root)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(480, 600)
        self.setMinimumSize(320, 360)

        ico_path = self._repo_root / "assets" / "icon.ico"
        if ico_path.is_file():
            self.setWindowIcon(QIcon(str(ico_path)))

        central = QWidget()
        central.setObjectName("ghostPanel")
        central.setStyleSheet(
            "#ghostPanel { background: rgba(10,10,10,200); border: 1px solid #00FF88; "
            "border-radius: 8px; }"
        )
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet("background:#141414; border-top-left-radius:7px; border-top-right-radius:7px;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 8, 0)

        title = QLabel(" GhostMind")
        title.setStyleSheet("color:#00FF88; font-weight: bold;")
        ui_font = QFont("Inter", 11)
        if QFontDatabase.hasFamily("Inter"):
            pass
        elif QFontDatabase.hasFamily("DM Sans"):
            ui_font = QFont("DM Sans", 11)
        else:
            ui_font = QFont("Segoe UI", 11)
        title.setFont(ui_font)

        btn_close = _RoundCtl("#FF4444")
        btn_close.clicked.connect(self.close)
        btn_min = _RoundCtl("#FFD54F")
        btn_min.clicked.connect(self._minimize_hide)
        btn_set = _RoundCtl("#00FF88")
        btn_set.clicked.connect(self._toggle_settings)

        hl.addWidget(btn_close)
        hl.addWidget(btn_min)
        hl.addWidget(btn_set)
        hl.addSpacing(8)
        hl.addWidget(title)
        hl.addStretch(1)

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
        hint = QLabel("Live transcription (Mic / System). Questions highlighted in gold.")
        hint.setStyleSheet("color:#888;font-size:11px;")
        sl.addWidget(hint)
        sl.addWidget(self._subtitle_bar, 1)

        self._tabs.addTab(self._answer_panel, "Answers")
        self._tabs.addTab(sub_host, "Subtitles")
        mp_lay.addWidget(self._tabs, 1)

        self._settings_panel = SettingsPanel(self._settings)
        self._settings_panel.hide()
        self._settings_panel.saved.connect(self._on_settings_saved)

        self._subtitle_bar.save_requested.connect(self.export_requested.emit)

        self._stack.addWidget(self._main_page)
        self._stack.addWidget(self._settings_panel)
        root.addWidget(self._stack, 1)

        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._trigger_scan)

        self._opacity_anim: Optional[QPropertyAnimation] = None
        self._apply_window_opacity(float(self._settings.get("opacity", 0.92)))

        self._header_drag = _HeaderDragFilter(self)
        header.installEventFilter(self._header_drag)

        self._apply_auto_timer_state()

    # --- public API for main.py ---
    def apply_settings(self, s: Dict[str, Any]) -> None:
        self._settings.update(s)
        self._apply_window_opacity(float(self._settings.get("opacity", 0.92)))
        self._apply_auto_timer_state()
        self._settings_panel.apply_data(self._settings)
        self._reapply_stealth()

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
        """Run Claude on arbitrary text (e.g. meeting transcript)."""
        if not (content or "").strip():
            return
        self._start_ai(content.strip(), context_type)

    def trigger_screen_scan(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            return
        mid = int(self._settings.get("monitor_id", 1))
        self._answer_panel.start_thinking()
        self._scan_worker = ScreenScanWorker(mid)
        self._scan_worker.finished_ok.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_fail)
        self._scan_worker.start()

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
            self._answer_panel.end_stream_error("OCR returned no text.")
            return
        self._start_ai(text, "screen")

    def _on_scan_fail(self, err: str) -> None:
        self._answer_panel.end_stream_error(f"OCR / capture error: {err}")

    def _start_ai(self, content: str, context_type: str) -> None:
        if self._ai_worker and self._ai_worker.isRunning():
            if context_type == "meeting_audio":
                return
            self._answer_panel.stop_thinking()
            self._answer_panel.end_stream_error("Already processing another answer.")
            return
        self._answer_panel.begin_answer_stream()
        self._ai_worker = AiStreamWorker(content, context_type)
        self._ai_worker.chunk_received.connect(self._answer_panel.append_stream_chunk)
        self._ai_worker.finished_ok.connect(self._answer_panel.end_stream_success)
        self._ai_worker.failed.connect(self._answer_panel.end_stream_error)
        self._ai_worker.finished.connect(self._ai_worker.deleteLater)
        self._ai_worker.start()

    def _apply_window_opacity(self, op: float) -> None:
        op = max(0.5, min(1.0, float(op)))
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
        QTimer.singleShot(0, self._reapply_stealth)

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self._reapply_stealth()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._reapply_stealth()

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
        if not self.close_event_allowed:
            e.ignore()
            self.closeRequested.emit()
        else:
            super().closeEvent(e)

    def leaveEvent(self, e) -> None:
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().leaveEvent(e)
