"""
Live subtitle ticker: last few lines, question highlighting, Mic/System labels.
"""
from __future__ import annotations

import re
from collections import deque
from typing import Deque

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget


_QUESTION_RE = re.compile(
    r"(^|\b)(who|what|when|where|why|how|could you|can you|should we|is it|are we)\b",
    re.IGNORECASE,
)


class SubtitleBar(QWidget):
    save_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lines: Deque[str] = deque(maxlen=6)
        self._view = QTextEdit()
        self._view.setReadOnly(True)
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setMinimumHeight(120)
        self._view.document().setDocumentMargin(8)
        self._view.setStyleSheet(
            "QTextEdit { background: #0D0D0D; color: #E0E0E0; border: 1px solid #1E1E1E; "
            "border-radius: 6px; font-size: 13px; }"
        )

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("Ctrl+Shift+E to export")
        hint.setStyleSheet("color:#555;font-size:10px;")
        header.addWidget(hint)
        header.addStretch(1)
        save_btn = QPushButton("Save")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            "QPushButton { background:#1A1A1A;color:#00FF88;border:none;padding:3px 10px;" font-size:11px; }"
            "QPushButton:hover { background:#252525; }"
        )
        save_btn.clicked.connect(self.save_requested.emit)
        header.addWidget(save_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(header)
        lay.addWidget(self._view)

    def append_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        self._lines.append(line)
        self._render()

    def clear(self) -> None:
        self._lines.clear()
        self._view.clear()

    def _render(self) -> None:
        visible = list(self._lines)[-4:]
        self._view.clear()
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)

        normal = QTextCharFormat()
        normal.setForeground(QColor("#E0E0E0"))

        label_fmt = QTextCharFormat()
        label_fmt.setForeground(QColor("#00FF88"))

        question_fmt = QTextCharFormat()
        question_fmt.setForeground(QColor("#FFD700"))

        for ln in visible:
            speaker = ""
            rest = ln
            if ln.startswith("Mic:"):
                speaker, rest = "Mic", ln[4:].strip()
            elif ln.startswith("System:"):
                speaker, rest = "System", ln[7:].strip()

            if speaker:
                cursor.setCharFormat(label_fmt)
                cursor.insertText(f"{speaker}: ")
            is_q = "?" in rest or bool(_QUESTION_RE.search(rest))
            cursor.setCharFormat(question_fmt if is_q else normal)
            cursor.insertText(rest + "\n")

        self._view.moveCursor(QTextCursor.MoveOperation.End)
        self._view.ensureCursorVisible()
