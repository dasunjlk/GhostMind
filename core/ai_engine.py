"""
Claude API integration with prompt routing and streaming via background worker.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from dotenv import load_dotenv
from PyQt6.QtCore import QObject, pyqtSignal, QThread

logger = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore

MODEL_ID = "claude-sonnet-4-20250514"
MAX_TOKENS = 1024

BASE_SYSTEM = (
    "You are GhostMind, a silent AI assistant. Respond concisely and clearly. "
    "Format your answer appropriately: use bullet points for lists, numbered steps "
    "for procedures, code blocks (wrapped in triple backticks with language tag) for code, "
    "and plain paragraphs for conversational answers. Never include preamble like 'Sure!' "
    "or 'Great question!'. Get straight to the answer."
)


def _classify_screen_text(content: str) -> str:
    c = content.lower()
    if any(k in c for k in ["a)", "b)", "c)", "d)", "multiple choice", "select one"]):
        return "quiz_mcq"
    if any(k in c for k in ["def ", "class ", "import ", "function", "```", "leetcode"]):
        return "coding"
    if "?" in content and len(content) < 4000:
        return "question"
    return "general"


def _screen_system_addon(kind: str) -> str:
    if kind == "quiz_mcq":
        return (
            " The user pasted screen text that looks like a quiz or multiple-choice question. "
            "Identify the best answer with a short justification."
        )
    if kind == "coding":
        return (
            " The user pasted a coding problem or code from the screen. "
            "Give a correct, minimal solution or fix with code in a fenced block."
        )
    if kind == "question":
        return " The user has a direct question in the screen text; answer it directly."
    return " Summarize or answer based on the screen content as appropriate."


def _meeting_system_block() -> str:
    return (
        BASE_SYSTEM
        + " You are given a live meeting transcript chunk. If a clear question was asked, "
        "answer it concisely. If there is no question, summarize key points in bullets."
    )


def build_system_prompt(context_type: str, content: str) -> str:
    if context_type == "meeting_audio":
        return _meeting_system_block()
    kind = _classify_screen_text(content)
    return BASE_SYSTEM + _screen_system_addon(kind)


def build_user_message(context_type: str, content: str) -> str:
    if context_type == "meeting_audio":
        return f"Transcript (may be partial):\n\n{content}"
    return f"Screen OCR text:\n\n{content}"


async def generate_answer(content: str, context_type: str = "screen") -> str:
    """Async API call (non-streaming); used for tests or direct await."""
    load_dotenv()
    if anthropic is None:
        raise RuntimeError("anthropic package not installed")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    client = anthropic.Anthropic(api_key=key)
    system = build_system_prompt(context_type, content)
    user_msg = build_user_message(context_type, content)
    msg = await asyncio.to_thread(
        lambda: client.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
    )
    parts = []
    for block in msg.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts).strip()


class AiStreamWorker(QThread):
    chunk_received = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, content: str, context_type: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._content = content
        self._context_type = context_type

    def run(self) -> None:
        load_dotenv()
        if anthropic is None:
            self.failed.emit("anthropic package not installed")
            return
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            self.failed.emit("ANTHROPIC_API_KEY is not set")
            return

        system = build_system_prompt(self._context_type, self._content)
        user_msg = build_user_message(self._context_type, self._content)
        client = anthropic.Anthropic(api_key=key)

        attempts = 0
        last_err: Optional[Exception] = None
        while attempts < 3:
            attempts += 1
            try:
                stream_mgr = client.messages.stream(
                    model=MODEL_ID,
                    max_tokens=MAX_TOKENS,
                    system=system,
                    messages=[{"role": "user", "content": user_msg}],
                )
                with stream_mgr as stream:
                    ts = getattr(stream, "text_stream", None)
                    if ts is None:
                        raise RuntimeError("Streaming API has no text_stream")
                    for text in ts:
                        if text:
                            self.chunk_received.emit(text)
                self.finished_ok.emit()
                return
            except Exception as e:
                last_err = e
                logger.warning("Anthropic stream failed (attempt %s): %s", attempts, e)
                try:
                    msg = client.messages.create(
                        model=MODEL_ID,
                        max_tokens=MAX_TOKENS,
                        system=system,
                        messages=[{"role": "user", "content": user_msg}],
                    )
                    parts = []
                    for block in msg.content:
                        if hasattr(block, "text"):
                            parts.append(block.text)
                    body = "".join(parts).strip()
                    if body:
                        self.chunk_received.emit(body)
                    self.finished_ok.emit()
                    return
                except Exception as e2:
                    last_err = e2
                    logger.warning("Anthropic non-stream fallback failed: %s", e2)
                time.sleep(0.75 * attempts)
        self.failed.emit(str(last_err) if last_err else "Unknown API error")
