"""
Groq API integration with prompt routing, fast streaming, and structured formatting.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from PyQt6.QtCore import QObject, pyqtSignal, QThread

logger = logging.getLogger(__name__)

try:
    from groq import Groq
except ImportError:  # pragma: no cover
    Groq = None  # type: ignore

try:
    from groq import RateLimitError  # type: ignore
except ImportError:  # pragma: no cover
    RateLimitError = None  # type: ignore

# Supported Models
DEFAULT_MODEL = "qwen/qwen3.8-27b"
MODEL_ID = DEFAULT_MODEL
BACKUP_MODELS: List[str] = [
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

AVAILABLE_MODELS: List[Tuple[str, str]] = [
    ("qwen/qwen3.8-27b", "Qwen 3.8 27B (Default)"),
    ("qwen/qwen3.6-27b", "Qwen 3.6 27B (Backup)"),
    ("openai/gpt-oss-120b", "GPT-OSS 120B"),
    ("openai/gpt-oss-20b", "GPT-OSS 20B (Fast)"),
]

# Sentinel itemData value for the settings dropdown "＋ Add custom model…" entry.
ADD_CUSTOM_MODEL_SENTINEL = "__add_custom_model__"

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


def resolve_api_key(explicit: Optional[str] = None) -> str:
    """API key lookup order: explicit argument -> keyring store -> env/.env."""
    key = (explicit or "").strip()
    if not key:
        try:
            from utils.key_store import load_key

            key = load_key().strip()
        except Exception as e:
            logger.warning("key_store load failed: %s", e)
    if not key:
        key = os.environ.get("GROQ_API_KEY", "").strip()
    return key


_NO_KEY_MSG = (
    "No API key found. Open Settings -> AI & API, paste your free key "
    "from https://console.groq.com, then Save."
)


def _classify_api_error(err: Exception) -> str:
    """Map a Groq client exception to a short, actionable user message."""
    text = str(err).lower()
    if (
        "401" in text
        or "invalid_api_key" in text
        or "invalid api key" in text
        or "unauthorized" in text
    ):
        return "API key was rejected - invalid or revoked. Double-check the key from https://console.groq.com"
    if any(
        s in text
        for s in ("connection", "timed out", "timeout", "getaddrinfo", "unreachable", "failed to resolve")
    ):
        return "Network error reaching Groq. Check your internet connection and try again."
    return f"Groq error: {str(err)[:200]}"


def validate_key_and_model(
    api_key: Optional[str] = None,
    model_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Verify the API key works AND that `model_id` is available to it.

    Uses one cheap `models.list` call (no chat completion, no token usage).
    Returns (ok, human-readable message) — never raises.
    """
    load_dotenv()
    key = resolve_api_key(api_key)
    if not key:
        return False, _NO_KEY_MSG
    if Groq is None:
        return False, "groq package is not installed. Install it with: pip install groq"
    try:
        client = Groq(api_key=key)
        models = client.models.list()
        ids = {m.id for m in (getattr(models, "data", None) or [])}
    except Exception as e:
        return False, _classify_api_error(e)
    model = (model_id or MODEL_ID).strip()
    if ids and model not in ids:
        return False, (
            f"Model '{model}' is not available with this API key. "
            "Pick a model from the list, or check the exact ID at https://console.groq.com/docs/models"
        )
    return True, f"API key works - '{model}' is ready."


def _get_client() -> Groq:
    load_dotenv()
    if Groq is None:
        raise RuntimeError(
            "groq package is not installed.\n"
            "Install it with: pip install groq"
        )
    key = resolve_api_key()
    if not key:
        raise RuntimeError(_NO_KEY_MSG)
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
    max_tokens = get_token_limit_for_context(context_type, content)
    primary = model_id or MODEL_ID
    models_to_try = [primary] + [m for m in BACKUP_MODELS if m != primary]
    last_err: Optional[Exception] = None

    for model in models_to_try:
        try:
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
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if "model_not_found" in err_str or "does not exist" in err_str or "404" in err_str:
                continue
            raise

    if last_err:
        raise last_err
    return ""


def _is_rate_limit_error(err: Exception) -> bool:
    """Return True if the exception looks like an HTTP 429 rate-limit error."""
    if RateLimitError is not None and isinstance(err, RateLimitError):
        return True
    response = getattr(err, "response", None)
    if getattr(response, "status_code", None) == 429:
        return True
    text = str(err).lower()
    return "429" in text or "rate limit" in text


def _rate_limit_backoff(err: Exception, attempt: int) -> float:
    """Seconds to wait before retrying after a rate-limit error.

    Honors the server's Retry-After header when present; otherwise backs off
    exponentially (1s, 2s, 4s, ...). Always capped at 30s.
    """
    delay = float(2 ** max(0, attempt - 1))
    response = getattr(err, "response", None)
    headers = getattr(response, "headers", None) or {}
    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if retry_after is not None:
        try:
            delay = max(delay, float(retry_after))
        except (TypeError, ValueError):
            pass
    return min(delay, 30.0)


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

        models_to_try = [self._model_id] + [m for m in BACKUP_MODELS if m != self._model_id]
        last_err: Optional[Exception] = None

        for model in models_to_try:
            attempts = 0
            while attempts < 4:  # 1 initial + up to 3 rate-limit retries
                attempts += 1
                try:
                    stream = client.chat.completions.create(
                        model=model,
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
                    logger.warning("Groq stream with model %s failed (attempt %s): %s", model, attempts, e)
                    err_str = str(e).lower()
                    if "model_not_found" in err_str or "does not exist" in err_str or "404" in err_str or "not have access" in err_str:
                        logger.warning("Model %s not found/accessible, trying next model...", model)
                        break
                    if _is_rate_limit_error(e):
                        if attempts > 3:
                            break  # give up on this model after the initial try + 3 retries
                        delay = _rate_limit_backoff(e, attempts)
                        logger.warning("Rate limited on %s; retrying in %.1fs", model, delay)
                        if delay > 3:
                            self.chunk_received.emit("\n\n(rate limited, retrying...)\n\n")
                        time.sleep(delay)
                        continue
                    # Fallback: non-streaming request
                    try:
                        resp = client.chat.completions.create(
                            model=model,
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
                        logger.warning("Groq non-stream fallback with model %s failed: %s", model, e2)
                        err_str2 = str(e2).lower()
                        if "model_not_found" in err_str2 or "does not exist" in err_str2 or "404" in err_str2 or "not have access" in err_str2:
                            break
                        if _is_rate_limit_error(e2):
                            if attempts > 3:
                                break
                            delay = _rate_limit_backoff(e2, attempts)
                            logger.warning("Rate limited (non-stream) on %s; retrying in %.1fs", model, delay)
                            if delay > 3:
                                self.chunk_received.emit("\n\n(rate limited, retrying...)\n\n")
                            time.sleep(delay)
                            continue
                    time.sleep(0.3 * attempts)

        self.failed.emit(str(last_err) if last_err else "Unknown API error")
