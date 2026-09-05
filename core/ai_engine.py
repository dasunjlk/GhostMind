"""
Groq API integration with prompt routing, fast streaming, and structured formatting.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Optional

from dotenv import load_dotenv
from PyQt6.QtCore import QObject, pyqtSignal, QThread

logger = logging.getLogger(__name__)

try:
    from groq import Groq
except ImportError:  # pragma: no cover
    Groq = None  # type: ignore

# Supported Groq Models
DEFAULT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"
MODEL_ID = DEFAULT_MODEL
MAX_TOKENS = 1024

BASE_SYSTEM = (
    "You are GhostMind, a silent stealth AI assistant. Respond concisely, accurately, and clearly. "
    "Get straight to the answer without conversational preamble (e.g. no 'Sure!', 'Here is', 'Certainly'). "
    "Use bullet points for lists, numbered steps for procedures, and code blocks with language tags for code."
)


def _classify_screen_text(content: str) -> str:
    c = content.lower()
    # MCQ / Quiz detection
    mcq_patterns = [
        r"\b[a-d]\s*[\)\.\:]",
        r"\([a-d]\)",
        r"\[[a-d]\]",
        r"multiple\s+choice",
        r"select\s+(one|the\s+best|all|correct)",
        r"which\s+of\s+the\s+following",
        r"true\s+or\s+false",
    ]
    if any(re.search(p, c) for p in mcq_patterns) or any(k in c for k in ["a)", "b)", "c)", "d)", "multiple choice", "select one"]):
        return "quiz_mcq"

    # Coding detection
    if any(k in c for k in ["def ", "class ", "import ", "function", "```", "leetcode", "return ", "public static void"]):
        return "coding"

    # Question detection
    if "?" in content and len(content) < 4000:
        return "question"

    return "general"


def _screen_system_addon(kind: str) -> str:
    if kind == "quiz_mcq":
        return (
            " The user pasted screen text that looks like a quiz or multiple-choice question. "
            "Identify the best answer with a short justification. Format your response strictly as:\n"
            "**Answer:** [Option Letter/Number] Option Text\n"
            "**Explanation:** 1-2 concise sentences explaining why this is correct."
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


def _lecture_system_block() -> str:
    return (
        BASE_SYSTEM
        + " You are given a lecture or class transcript. Structure your output clearly:\n"
        "# Lecture Summary\n"
        "## Core Concepts\n"
        "Bullet points of what the lecturer is explaining.\n"
        "## Key Takeaways & Definitions\n"
        "Definitions, formulas, or critical points mentioned."
    )


def _meeting_question_system_block() -> str:
    return (
        BASE_SYSTEM
        + " The user is in a live meeting and a direct question was asked by a participant or speaker. "
        "Provide a direct, high-value, factual answer immediately in 1-3 sentences. No fluff."
    )


def build_system_prompt(context_type: str, content: str) -> str:
    if context_type == "meeting_audio":
        return _meeting_system_block()
    if context_type == "meeting_question":
        return _meeting_question_system_block()
    if context_type in ("lecture_notes", "lecture_audio"):
        return _lecture_system_block()
    kind = _classify_screen_text(content)
    return BASE_SYSTEM + _screen_system_addon(kind)


def build_user_message(context_type: str, content: str) -> str:
    if context_type in ("meeting_audio", "meeting_summary"):
        return f"Transcript (may be partial):\n\n{content}"
    if context_type == "meeting_question":
        return f"Live Question asked during meeting:\n\n{content}"
    if context_type in ("lecture_notes", "lecture_audio"):
        return f"Lecture audio transcript:\n\n{content}"
    return f"Screen OCR text:\n\n{content}"


def _get_client() -> Groq:
    load_dotenv()
    if Groq is None:
        raise RuntimeError(
            "groq package is not installed.\n"
            "Install it with: pip install groq"
        )
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY is not set.\n"
            "Get a free key at https://console.groq.com and add it to your .env file."
        )
    return Groq(api_key=key)


def get_token_limit_for_context(context_type: str, content: str) -> int:
    """Choose optimal max_tokens to minimize latency."""
    if context_type == "meeting_question":
        return 350
    kind = _classify_screen_text(content)
    if kind == "quiz_mcq":
        return 450
    if context_type in ("lecture_notes", "lecture_audio", "meeting_summary"):
        return 1200
    return MAX_TOKENS


async def generate_answer(
    content: str,
    context_type: str = "screen",
    model_id: Optional[str] = None,
) -> str:
    """Async API call (non-streaming); used for tests or direct await."""
    client = _get_client()
    system = build_system_prompt(context_type, content)
    user_msg = build_user_message(context_type, content)
    model = model_id or MODEL_ID
    max_tokens = get_token_limit_for_context(context_type, content)
    msg = await asyncio.to_thread(
        lambda: client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.3,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
        )
    )
    return (msg.choices[0].message.content or "").strip()


class AiStreamWorker(QThread):
    chunk_received = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(
        self,
        content: str,
        context_type: str,
        model_id: Optional[str] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._content = content
        self._context_type = context_type
        self._model_id = model_id or MODEL_ID

    def run(self) -> None:
        try:
            client = _get_client()
        except Exception as e:
            self.failed.emit(str(e))
            return

        system = build_system_prompt(self._context_type, self._content)
        user_msg = build_user_message(self._context_type, self._content)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]
        max_tokens = get_token_limit_for_context(self._context_type, self._content)

        attempts = 0
        last_err: Optional[Exception] = None
        while attempts < 3:
            attempts += 1
            try:
                stream = client.chat.completions.create(
                    model=self._model_id,
                    max_tokens=max_tokens,
                    temperature=0.3,
                    messages=messages,
                    stream=True,
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        self.chunk_received.emit(chunk.choices[0].delta.content)
                self.finished_ok.emit()
                return
            except Exception as e:
                last_err = e
                logger.warning("Groq stream failed (attempt %s): %s", attempts, e)
                # Fallback: non-streaming request
                try:
                    resp = client.chat.completions.create(
                        model=self._model_id,
                        max_tokens=max_tokens,
                        temperature=0.3,
                        messages=messages,
                    )
                    body = (resp.choices[0].message.content or "").strip()
                    if body:
                        self.chunk_received.emit(body)
                    self.finished_ok.emit()
                    return
                except Exception as e2:
                    last_err = e2
                    logger.warning("Groq non-stream fallback failed: %s", e2)
                time.sleep(0.5 * attempts)
        self.failed.emit(str(last_err) if last_err else "Unknown API error")
