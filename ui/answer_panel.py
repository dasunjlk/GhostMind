"""
Scrollable answer history with markdown-like rendering, streaming support, copy actions.
"""
from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from utils.formatter import parse_and_render


class _ThinkingDots(QWidget):
    """Three pulsing dots while the model is generating."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._label = QLabel("Thinking")
        self._label.setStyleSheet("color:#888;font-style:italic;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.addWidget(self._label)
        self._phase = 0
        self._timer = None

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(400)
        else:
            self._timer.start(400)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        if self._timer:
            self._timer.stop()

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 4
        dots = "." * self._phase
        self._label.setText(f"Thinking{dots}")


class _AnswerBlock(QWidget):
    copy_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._raw_markdown = ""
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFrameShape(QFrame.Shape.NoFrame)
        self._text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._text.document().setDocumentMargin(8)
        self._text.setStyleSheet(
            "QTextEdit { background: transparent; color: #E0E0E0; "
            "border: 1px solid #222; border-radius: 6px; }"
        )

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet(
            "QPushButton { background:#1A1A1A;color:#00FF88;border:none;padding:4px 10px; }"
            "QPushButton:hover { background:#252525; }"
        )
        self._copy_btn.clicked.connect(self._on_copy)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._copy_btn)

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 8)
        v.addWidget(self._text)
        v.addLayout(row)

    def _on_copy(self) -> None:
        self.copy_requested.emit(self._raw_markdown or self._text.toPlainText())

    def set_html(self, html: str) -> None:
        self._text.setHtml(html)
        self._text.document().adjustSize()
        h = int(self._text.document().size().height()) + 24
        self._text.setMinimumHeight(min(max(h, 80), 1200))

    def set_streaming_plain(self, text: str) -> None:
        self._raw_markdown = text
        self._text.setPlainText(text)
        self._text.moveCursor(QTextCursor.MoveOperation.End)
        doc_h = int(self._text.document().size().height()) + 24
        self._text.setMinimumHeight(min(max(doc_h, 60), 1200))

    def finalize_markdown(self, md: str) -> None:
        self._raw_markdown = md
        self.set_html(parse_and_render(md))


class AnswerPanel(QWidget):
    """Hosts multiple answer blocks, thinking state, and clear control."""

    clear_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._blocks: List[_AnswerBlock] = []
        self._current_block: Optional[_AnswerBlock] = None
        self._stream_buffer = ""
        self._thinking: Optional[_ThinkingDots] = None

        header = QHBoxLayout()
        title = QLabel("Answers")
        title.setStyleSheet("color:#00FF88;font-weight:bold;")
        clear_btn = QPushButton("Clear")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(
            "QPushButton { background:#1A1A1A;color:#E0E0E0;border:none;padding:4px 12px; }"
            "QPushButton:hover { background:#2A2A2A; }"
        )
        clear_btn.clicked.connect(self._on_clear)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(clear_btn)

        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.setContentsMargins(0, 0, 0, 0)
        self._inner_layout.setSpacing(8)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(self._inner)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 4px; background: #111; }"
            "QScrollBar::handle:vertical { background: #00FF88; min-height: 20px; border-radius: 2px; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(header)
        root.addWidget(self._scroll, 1)

    def _on_clear(self) -> None:
        self.clear_all()
        self.clear_clicked.emit()

    def clear_all(self) -> None:
        self._stream_buffer = ""
        self._current_block = None
        self._hide_thinking()
        for b in self._blocks:
            b.deleteLater()
        self._blocks.clear()
        while self._inner_layout.count():
            item = self._inner_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def start_thinking(self) -> None:
        self._hide_thinking()
        self._stream_buffer = ""
        self._thinking = _ThinkingDots(self._inner)
        self._inner_layout.addWidget(self._thinking)
        self._scroll_to_bottom()

    def stop_thinking(self) -> None:
        """Remove the thinking indicator without starting an answer stream."""
        self._hide_thinking()

    def _hide_thinking(self) -> None:
        if self._thinking:
            self._thinking.deleteLater()
            self._thinking = None

    def begin_answer_stream(self) -> None:
        self._hide_thinking()
        self._stream_buffer = ""
        block = _AnswerBlock(self._inner)
        block.copy_requested.connect(self._copy_to_clipboard)
        self._inner_layout.addWidget(block)
        self._blocks.append(block)
        self._current_block = block
        self._scroll_to_bottom()

    def append_stream_chunk(self, chunk: str) -> None:
        self._stream_buffer += chunk
        if self._current_block:
            self._current_block.set_streaming_plain(self._stream_buffer)
            self._scroll_to_bottom()

    def end_stream_success(self) -> None:
        if self._current_block:
            self._current_block.finalize_markdown(self._stream_buffer)
        self._current_block = None
        self._stream_buffer = ""

    def end_stream_error(self, message: str) -> None:
        self._hide_thinking()
        if self._current_block:
            self._current_block.set_html(f"<p style='color:#FF4444;'>{message}</p>")
        else:
            block = _AnswerBlock(self._inner)
            block.set_html(f"<p style='color:#FF4444;'>{message}</p>")
            self._inner_layout.addWidget(block)
            self._blocks.append(block)
        self._current_block = None
        self._stream_buffer = ""
        self._scroll_to_bottom()

    def _copy_to_clipboard(self, text: str) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
