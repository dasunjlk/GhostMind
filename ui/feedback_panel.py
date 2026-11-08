"""In-app user feedback tab (C13): type, rating, message, optional contact.

Send runs off the GUI thread (same daemon-thread + signals pattern as the
API-key check in Settings). utils/feedback.submit_feedback owns the privacy
rules (scrubbing, opt-out, outbox) — this widget only collects, reports the
result honestly, and offers the copy-to-clipboard fallback.
"""
from __future__ import annotations

import threading
from typing import Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from utils import feedback
from version import __version__

_TYPE_BTN_CSS = (
    "QPushButton{background:#141414;color:#CCCCCC;border:1px solid #333;"
    "border-radius:14px;font-size:11.5px;padding:5px 12px;}"
    "QPushButton:hover{background:#1E1E1E;}"
    "QPushButton:checked{background:#162B1E;color:#00FF88;border-color:#00FF88;}"
)
_FACE_BTN_CSS = (
    "QPushButton{background:#141414;border:1px solid #333;border-radius:8px;"
    "font-size:17px;min-width:34px;min-height:34px;}"
    "QPushButton:hover{background:#1E1E1E;}"
    "QPushButton:checked{background:#162B1E;border-color:#00FF88;}"
)


class _FeedbackSignals(QObject):
    done = pyqtSignal(bool, str)  # ok, user-facing message


class FeedbackPanel(QWidget):
    """The visible Feedback tab in Settings."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        intro = QLabel(
            "Tell us what you think — bugs, ideas, or anything else. It all helps."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#CCCCCC;font-size:12px;")
        root.addWidget(intro)

        # --- Type selector (exactly one) ---
        self._type_group = QButtonGroup(self)
        self._type_group.setExclusive(True)
        type_row = QHBoxLayout()
        type_row.setSpacing(6)
        for i, (label, key) in enumerate(
            [
                ("👍 Works great", "works_great"),
                ("🐞 Something broke", "bug"),
                ("💡 Suggestion", "suggestion"),
                ("❓ Other", "other"),
            ]
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_TYPE_BTN_CSS)
            btn.setProperty("feedbackType", key)
            self._type_group.addButton(btn)
            type_row.addWidget(btn)
        type_row.addStretch(1)
        root.addLayout(type_row)

        # --- Optional rating (one face; click the selected face to clear) ---
        rating_lbl = QLabel("How is GhostMind treating you? (optional)")
        rating_lbl.setStyleSheet("color:#888888;font-size:11px;")
        root.addWidget(rating_lbl)
        self._rating_group = QButtonGroup(self)
        self._rating_group.setExclusive(False)
        self._rating_buttons: list[QPushButton] = []
        rating_row = QHBoxLayout()
        rating_row.setSpacing(6)
        for value, face in enumerate(["😍", "🙂", "😐", "🙁", "😡"], start=1):
            btn = QPushButton(face)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_FACE_BTN_CSS)
            btn.setProperty("rating", value)
            btn.clicked.connect(self._on_rating_clicked)
            self._rating_group.addButton(btn)
            self._rating_buttons.append(btn)
            rating_row.addWidget(btn)
        rating_row.addStretch(1)
        root.addLayout(rating_row)

        # --- Optional message + contact ---
        self._text = QPlainTextEdit()
        self._text.setPlaceholderText("What happened? What did you expect? (optional)")
        self._text.setMaximumHeight(88)
        self._text.setStyleSheet(
            "QPlainTextEdit{background:#141414;color:#E0E0E0;border:1px solid #333;"
            "border-radius:6px;font-size:12px;}"
        )
        root.addWidget(self._text)

        self._contact = QLineEdit()
        self._contact.setPlaceholderText("Email — only if you want a reply (optional)")
        self._contact.setStyleSheet(
            "QLineEdit{background:#141414;color:#E0E0E0;border:1px solid #333;"
            "border-radius:6px;font-size:12px;padding:6px 9px;}"
        )
        root.addWidget(self._contact)

        # --- What gets sent (honesty line) ---
        self._what = QLabel(
            f"Sends anonymously: GhostMind {__version__} · {feedback.os_label()} "
            f"· ID {feedback.install_id_prefix()}…"
        )
        self._what.setWordWrap(True)
        self._what.setStyleSheet("color:#888888;font-size:11px;")
        root.addWidget(self._what)

        # --- Actions ---
        actions = QHBoxLayout()
        self._copy_btn = QPushButton("Copy feedback")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setToolTip(
            "Copy this feedback as text — handy for GitHub issues when "
            "anonymous reporting is disabled."
        )
        self._copy_btn.setStyleSheet(
            "QPushButton{background:#1A1A1A;color:#CCCCCC;border:1px solid #333;"
            "padding:7px 14px;border-radius:4px;font-size:11.5px;}"
            "QPushButton:hover{background:#252525;}"
        )
        self._copy_btn.clicked.connect(self._copy_feedback)
        actions.addWidget(self._copy_btn)

        actions.addStretch(1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#777777;font-size:11px;")
        actions.addWidget(self._status)

        self._send_btn = QPushButton("Send anonymously")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet(
            "QPushButton{background:#00FF88;color:#0A0A0A;border:none;"
            "padding:7px 18px;font-weight:bold;border-radius:4px;}"
            "QPushButton:hover{background:#33FFAA;}"
            "QPushButton:disabled{background:#333;color:#777;}"
        )
        self._send_btn.clicked.connect(self._on_send)
        actions.addWidget(self._send_btn)
        root.addLayout(actions)

    # ------------------------------------------------------------ helpers --

    def _selected_type(self) -> str:
        btn = self._type_group.checkedButton()
        return str(btn.property("feedbackType")) if btn is not None else "other"

    def _selected_rating(self) -> Optional[int]:
        for btn in self._rating_buttons:
            if btn.isChecked():
                return int(btn.property("rating"))
        return None

    def _on_rating_clicked(self) -> None:
        clicked = self.sender()
        for btn in self._rating_buttons:
            if btn is not clicked:
                btn.setChecked(False)

    def _summary_text(self) -> str:
        rating = self._selected_rating()
        contact = self._contact.text().strip()
        rating_line = f"Rating: {rating}/5\n" if rating else "Rating: -\n"
        return (
            "GhostMind feedback\n"
            f"Type: {self._selected_type()}\n"
            + rating_line
            + f"Message: {self._text.toPlainText().strip() or '(none)'}\n"
            f"Contact: {contact or '(none)'}\n"
            f"App: {__version__} · {feedback.os_label()}"
        )

    def _copy_feedback(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._summary_text())
            self._status.setText("Copied — paste it into a GitHub issue.")
            self._status.setStyleSheet("color:#777777;font-size:11px;")

    # -------------------------------------------------------------- send --

    def _on_send(self) -> None:
        payload = feedback.build_payload(
            self._selected_type(),
            self._selected_rating(),
            self._text.toPlainText(),
            self._contact.text(),
        )
        self._send_btn.setEnabled(False)
        self._status.setText("Sending…")
        self._status.setStyleSheet("color:#FFAA00;font-size:11px;")
        signals = _FeedbackSignals(self)
        signals.done.connect(self._on_send_done)

        def _work() -> None:
            ok, msg = feedback.submit_feedback(payload)
            signals.done.emit(ok, msg)

        threading.Thread(target=_work, daemon=True).start()

    def _on_send_done(self, ok: bool, msg: str) -> None:
        self._send_btn.setEnabled(True)
        if ok:
            self._text.clear()
            self._contact.clear()
            for btn in self._rating_buttons:
                btn.setChecked(False)
            self._status.setText("✓ Sent - thank you!")
            self._status.setStyleSheet("color:#00FF88;font-size:11px;")
        else:
            self._status.setText(f"● {msg}")
            self._status.setStyleSheet("color:#FF5555;font-size:11px;")
