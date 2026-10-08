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
    pyqtSlot,
)
from PyQt6.QtGui import QCursor, QFont, QFontDatabase, QIcon, QKeyEvent, QMouseEvent, QPainter
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

from core.ai_engine import AiStreamWorker, DEFAULT_MODEL
from core.screen_reader import ScreenScanWorker
from core.stealth import apply_stealth


def _is_worker_active(worker: Any | None) -> bool:
    """Lightweight safety probe used by tests."""
    if worker is None:
        return False
    try:
        return bool(worker.isRunning())
    except Exception:
        return False


def _is_worker_active_deleted_worker_probe() -> None:
    """Used only to verify the helper path; not part of the runtime flow."""
    pass



from ui.answer_panel import AnswerPanel
from ui.settings_panel import SettingsPanel
from ui.subtitle_bar import SubtitleBar



class _OnboardingGuide(QWidget):
    """Modern, arrow-anchored first-run hint popup.

    It is frameless, auto-hiding, and moves near a target widget on demand.
    It also exposes a close button so the user can dismiss it early.
    """

    shown = pyqtSignal()
    dismissed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(280, 0)  # height adjusts per message
        self._arrow_size = 14
        self._current_target: QWidget | None = None
        self._anim: QVariantAnimation | None = None
        self._visible = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._arrow = QLabel()
        self._arrow.setFixedSize(self._arrow_size, self._arrow_size)
        self._arrow.setStyleSheet(
            "background:#00FF88; border-radius:3px;"
        )
        lay.addWidget(self._arrow, 0, Qt.AlignmentFlag.AlignLeft)

        self._body = QLabel("", alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._body.setStyleSheet(
            "color:#E0E0E0; background:#222; border:1px solid #00FF88; border-radius:6px;"
            " padding:10px 12px; font-size:12px; word-wrap:break-word;"
        )
        self._body.setWordWrap(True)
        lay.addWidget(self._body, 0, Qt.AlignmentFlag.AlignLeft)

        close_row = QHBoxLayout()
        close_row.setContentsMargins(0, 0, 0, 0)
        close_row.addStretch(1)
        btn_close = QPushButton("×")
        btn_close.setFixedSize(18, 18)
        btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close.setStyleSheet(
            "QPushButton { color:#888; background:#222; border:none; font-size:14px; }"
            "QPushButton:hover { color:#00FF88; background:#333; }"
        )
        btn_close.clicked.connect(self._dismiss)
        close_row.addWidget(btn_close)
        lay.addLayout(close_row)

    def _dismiss(self) -> None:
        self.hide_guide()
        self.dismissed.emit()

    def set_message(self, text: str, caption: str = "Hint") -> None:
        self._body.setText(f"<b>{caption}</b> — {text}")
        hint_height = self._body.fontMetrics().boundingRect(
            Qt.TextElideMode.NoElide, QRect(0, 0, 250, 0), text
        ).height() + 54
        self.setFixedHeight(max(60, hint_height))

    def show_guide(self) -> None:
        if not self._visible:
            self._visible = True
            self.show()
            self.raise_()
            self.setAttribute(Qt.WidgetAttribute.WA_MouseLeavesEvent, True)

    def hide_guide(self) -> None:
        if self._visible:
            self._visible = False
            self.hide()

    def fire_near_settings(self) -> None:
        """First-use guide anchored near the Settings button the user just opened."""
        if not self.parent():
            return
        target = self.parent()
        self._current_target = target
        self.set_message(
            "To add your API key first, go to Settings → API and paste a free key from https://console.groq.com.",
            caption="Welcome",
        )
        self._place_near(target)
        self.show_guide()
        self.shown.emit()

    def _place_near(self, anchor: QWidget) -> None:
        if not anchor or not anchor.isVisible():
            return
        screen = anchor.windowHandle().screen() if getattr(anchor, "windowHandle", None) else None
        base = anchor.mapToGlobal(QPoint(0, 0))
        margin = 8
        arrow_right = self._arrow_size + 4
        preferred_x = max(0, base.x() - self.width() - arrow_right - margin)
        preferred_y = base.y() + 8
        geom = QRect(preferred_x, preferred_y, self.width(), self.height())
        if screen:
            geo = screen.availableGeometry()
            geom.setBottom(min(geom.bottom(), geo.bottom() - 8))
            geom.setLeft(max(geom.left(), geo.left() + 8))
            geom.setRight(min(geom.right(), geo.right() - 8))
        self.setGeometry(geom)

    def leaveEvent(self, e) -> None:
        if self._visible:
            self._dismiss()
        super().leaveEvent(e)


from core.ai_engine import AiStreamWorker, DEFAULT_MODEL



class _ResizeEdge(IntFlag):
    NONE = 0
    LEFT = auto()
    RIGHT = auto()
    TOP = auto()
    BOTTOM = auto()


class _HeaderDragFilter(QObject):
    """Allows dragging the frameless window by its header."""

    def __init__(self, overlay: QMainWindow, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._overlay = overlay

    def eventFilter(self, a0, a1) -> bool:
        if a1.type() == QEvent.Type.MouseButtonPress and a0.objectName() == "header":
            self._drag_start = a0.globalPosition().toPoint()
            self._geom_start = self._overlay.geometry()
            return True
        if a1.type() == QEvent.Type.MouseMove and self._drag_start is not None:
            delta = a0.globalPosition().toPoint() - self._drag_start
            geom = self._geom_start.translated(delta)
            self._overlay.setGeometry(geom)
            return True
        if a1.type() == QEvent.Type.MouseButtonRelease:
            self._drag_start = None
            return True
        return super().eventFilter(a0, a1)


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

    def mousePressEvent(self, a0) -> None:
        self._on = not self._on
        self.update()
        self.setToolTip(self._tooltip_text())
        self.toggled.emit(self._on)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = self.width() / 2, self.height() / 2, 9
        if self._kind == "mic":
            p.setPen(QPen(QColor("#00FF88"), 2))
            p.drawEllipse(cx, cy - 4, r, r)
            p.drawLine(cx, cy - 12, cx, cy - r - 3)
        else:
            p.setPen(QPen(QColor("#00FF88"), 2))
            p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 0, 512)
            p.drawRect(cx - 3, cy - 8, 6, 16)
        if not self._on:
            p.setPen(QPen(QColor("#FF5555"), 2.4))
            p.drawLine(3, 3, self.width() - 3, self.height() - 3)
        if self._kind == "mic" and not self._has_device:
            p.setPen(QPen(QColor("#FFAA00"), 2))
            p.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignmentFlag.AlignCenter, "!")


class OverlayWindow(QMainWindow):
    """Main frameless overlay window.

    It has a minimal chrome header, tabs, and a settings panel stack page.
    """

    settings_changed = pyqtSignal(dict)
    closeRequested = pyqtSignal()
    export_requested = pyqtSignal()
    summarize_meeting_requested = pyqtSignal()

    def __init__(self, settings: Dict[str, Any], repo_root: Path) -> None:
        super().__init__()
        self._settings = dict(settings)
        self._repo_root = repo_root
        self.setWindowTitle("GhostMind")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)

        self._opacity_anim: Optional[QVariantAnimation] = None
        self._visible_target = False
        self._fade_target: Optional[float] = None
        self._auto_timer: QTimer
        self._settings_panel: SettingsPanel
        self._tabs: QTabWidget
        self._answer_panel: AnswerPanel
        self._subtitle_bar: SubtitleBar
        self._stack: QStackedWidget
        self._geometry_save_timer: QTimer
        self._header_drag: _HeaderDragFilter
        self._mic_toggle: _CaptureIconWidget
        self._sys_toggle: _CaptureIconWidget
        self._has_microphone: Optional[bool] = None
        self._onboarding: _OnboardingGuide
        self._onboarding_button: QPushButton
        self.close_event_allowed = False

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
        header.setObjectName("header")
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

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(24, 24)
        btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close.setStyleSheet(
            "QPushButton { background:#FF4444; color:#fff; border:none; border-radius:12px; font-size:12px; }"
            "QPushButton:hover { background:#FF6B6B; }"
        )
        btn_close.setToolTip("Close to tray")
        btn_close.clicked.connect(self._minimize_hide)

        btn_min = QPushButton("—")
        btn_min.setFixedSize(24, 24)
        btn_min.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_min.setStyleSheet(
            "QPushButton { background:#333; color:#fff; border:none; border-radius:12px; font-size:14px; }"
            "QPushButton:hover { background:#555; }"
        )
        btn_min.setToolTip("Minimize")
        btn_min.clicked.connect(self._minimize_hide)

        # Settings Gear Icon Button
        btn_set = QPushButton("⚙")
        btn_set.setToolTip("Settings")
        btn_set.setFixedSize(26, 26)
        btn_set.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_set.setStyleSheet(
            "QPushButton { background: transparent; color: #888888; border: none; font-size: 15px; border-radius: 4px; padding-bottom: 2px; }"
            "QPushButton:hover { background: #222222; color: #00FF88; }"
        )
        btn_set.clicked.connect(self._on_settings_button_clicked)

        hl.addWidget(btn_close)
        hl.addWidget(btn_min)
        hl.addSpacing(8)
        hl.addWidget(title)
        hl.addStretch(1)
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

        self._settings_panel = SettingsPanel(self._settings)
        self._settings_panel.hide()
        self._settings_panel.saved.connect(self._on_settings_saved)
        self._settings_panel.opacity_preview.connect(self._apply_window_opacity)
        self._settings_panel._view_guide_requested.connect(self._on_settings_guide_requested)
        self._settings_panel._overlay_ref = self

        self._subtitle_bar.save_requested.connect(self.export_requested.emit)
        self._subtitle_bar.summarize_requested.connect(self.summarize_meeting_requested.emit)

        self._stack.addWidget(self._main_page)
        self._stack.addWidget(self._settings_panel)
        root.addWidget(self._stack, 1)

        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._trigger_scan)

        self._opacity_anim: Optional[QVariantAnimation] = None
        self._apply_window_opacity(float(self._settings.get("opacity", 0.92)))

        self._header_drag = _HeaderDragFilter(self)
        header.installEventFilter(self._header_drag)

        self._apply_auto_timer_state()

        # First-run onboarding (v1.0): modern arrow-anchored popup near Settings.
        self._onboarding = _OnboardingGuide(self)
        self._onboarding_button = btn_set

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
        """Run Groq on arbitrary text (e.g. meeting question or transcript)."""
        if not (content or "").strip():
            return
        worker = AiStreamWorker(
            content=content,
            context_type=context_type,
            model_id=self._settings.get("ai_model", DEFAULT_MODEL),
            settings=self._settings,
        )
        worker.moveToThread(worker)
        worker.finished.connect(self._answer_panel.append_block)
        worker.error.connect(self._answer_panel.end_stream_error)
        worker.start()
        self._current_worker = worker

    def trigger_screen_scan(self) -> None:
        """OCR current monitor and send result to AI."""
        monitors = []
        try:
            from core.screen_reader import get_monitors

            monitors = get_monitors()
        except Exception as e:  # never let OCR probe break the UI
            self._answer_panel.end_stream_error(f"Screen capture unavailable: {e}")
            return
        target_id = int(self._settings.get("monitor_id", 1))
        mon = next((m for m in monitors if int(m.get("id", -1)) == target_id), None)
        if mon is None:
            self._answer_panel.end_stream_error(f"Monitor {target_id} not found")
            return
        worker = ScreenScanWorker(mon["id"])
        worker.moveToThread(worker)
        worker.text_ready.connect(self._on_scan_done)
        worker.error.connect(self._answer_panel.end_stream_error)
        worker.start()

    def clear_answers(self) -> None:
        self._answer_panel.clear()

    def toggle_subtitles_tab(self) -> None:
        if not self._subtitle_bar.isVisible():
            self._subtitle_bar.show()
        else:
            self._subtitle_bar.hide()

    # --- internal helpers ---
    def _on_settings_button_clicked(self) -> None:
        if self._stack.currentIndex() == 1:
            self._stack.setCurrentIndex(0)
            self._settings_panel.hide()
        else:
            self._settings_panel.apply_data(self._settings)
            self._stack.setCurrentIndex(1)
            self._settings_panel.show()
            self._onboarding.fire_near_settings()

    def _on_settings_guide_requested(self) -> None:
        """Replay the first-run guide near the Settings button."""
        self._onboarding.fire_near_settings()

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
            self._answer_panel.end_stream_error("No text found on screen")
            return
        self.request_ai_answer(text, "screen")

    def _minimize_hide(self) -> None:
        self._fade_to(0.0, hide_on_finish=True)

    def _fade_to(self, target: float, hide_on_finish: bool = False) -> None:
        if self._opacity_anim is not None and self._opacity_anim.state() == QVariantAnimation.State.Running:
            self._opacity_anim.stop()
        self._fade_target = target
        current = self.windowOpacity()
        self._opacity_anim = QVariantAnimation(current, target, 120)
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._opacity_anim.valueChanged.connect(self._on_opacity_frame)
        if hide_on_finish:
            self._opacity_anim.finished.connect(self._on_fade_finished)
            self._opacity_anim.finished.connect(self._opacity_anim.deleteLater)
        self._opacity_anim.start()

    def _on_opacity_frame(self, value: float) -> None:
        self.setWindowOpacity(max(0.0, min(1.0, value)))

    def _on_fade_finished(self) -> None:
        if self._fade_target == 0.0:
            self.hide()
        self._fade_target = None

    def _reapply_stealth(self) -> None:
        try:
            hwnd = int(self.winId())
            apply_stealth(
                hwnd,
                click_through=bool(self._settings.get("click_through", False)),
                dwm_cloak=bool(self._settings.get("dwm_cloak", False)),
            )
        except Exception as e:
            pass

    def set_microphone_available(self, available: bool) -> None:
        """Mark whether the machine has a microphone for the header badge."""
        if self._has_microphone != bool(available):
            self._has_microphone = bool(available)
            if self._mic_toggle is not None:
                self._mic_toggle.set_has_device(self._has_microphone)

    def _apply_window_opacity(self, opacity: float) -> None:
        value = max(0.1, min(1.0, float(opacity)))
        self.setWindowOpacity(value)
        self._settings["opacity"] = value

    def _schedule_geometry_save(self) -> None:
        if self._geometry_save_timer is None:
            self._geometry_save_timer = QTimer(self)
            self._geometry_save_timer.setSingleShot(True)
            self._geometry_save_timer.timeout.connect(self._flush_geometry_save)
        self._geometry_save_timer.start(400)

    def _flush_geometry_save(self) -> None:
        self._settings["window_x"] = self.x()
        self._settings["window_y"] = self.y()
        self._settings["window_w"] = self.width()
        self._settings["window_h"] = self.height()
        screen = self.screen()
        self._settings["window_screen"] = screen.name() if screen is not None else None

    def _restore_window_geometry(self) -> None:
        sx = self._settings.get("window_x")
        sy = self._settings.get("window_y")
        sw = self._settings.get("window_w")
        sh = self._settings.get("window_h")
        try:
            if isinstance(sx, int) and isinstance(sy, int):
                self.move(sx, sy)
            if isinstance(sw, int) and isinstance(sh, int):
                self.resize(sw, sh)
        except Exception:
            pass
        self._schedule_geometry_save()

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        self._schedule_geometry_save()

    def moveEvent(self, e: QMouseEvent) -> None:
        super().moveEvent(e)
        self._schedule_geometry_save()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        super().mouseReleaseEvent(e)

    def closeEvent(self, e) -> None:
        """Intercept close: hide to tray unless close_event_allowed is True."""
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
                self._on_settings_button_clicked()
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
