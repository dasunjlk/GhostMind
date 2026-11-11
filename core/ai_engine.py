"""
OpenAI-compatible AI engine with prompt routing, streaming, and structured formatting.

The provider is selected entirely by `base_url`, so Groq, OpenRouter, and any
other OpenAI-compatible chat-completions endpoint work without code changes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv
from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore

try:
    from openai import RateLimitError  # type: ignore
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

# Default provider. `base_url` is the only switch between providers; no
# provider-specific branching exists outside the Groq backup-model cascade.
DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"

# Determinism: providers honor `seed` best-effort. Combined with temperature 0
# this makes repeated questions return stable answers.
DETERMINISTIC_TEMPERATURE = 0.0
DETERMINISTIC_SEED = 7

MAX_TOKENS = 1024

# Approximate visible tokens in the answer viewport of the default 480x600
# overlay at the default font (462x446 viewport -> 250). Used to scale answer
# length with the window size (see estimate_visible_tokens).
DEFAULT_CAPACITY = 250
_MIN_CAPACITY_FACTOR = 0.5
_MAX_CAPACITY_FACTOR = 2.0

BASE_SYSTEM = (
    "You are GhostMind, a silent stealth AI assistant. Respond concisely, accurately, and clearly. "
    "Get straight to the answer without conversational preamble (e.g. no 'Sure!', 'Here is', 'Certainly'). "
    "Use bullet points for lists, numbered steps for procedures, and code blocks with language tags for code."
)


def estimate_visible_tokens(width_px: int, height_px: int, font_pt: int) -> int:
    """Approximate how many tokens the answer viewport can show at once.

    Rough model: line height ~= 1.6 x font size, ~4 characters per token, and
    ~90px of chrome (header, buttons) that never displays answer text.
    """
    pt = max(8, int(font_pt))
    line_h = pt * 1.6
    usable_h = max(0.0, float(height_px) - 90.0)
    lines = max(3, int(usable_h / line_h))
    chars_per_line = max(24, int(int(width_px) / (pt * 0.6)))
    return int(lines * chars_per_line / 4)


def _capacity_factor(capacity: Optional[int]) -> float:
    """Map visible capacity to a 0.5x-2x multiplier around the default size."""
    if capacity is None or capacity <= 0:
        return 1.0
    return max(_MIN_CAPACITY_FACTOR, min(_MAX_CAPACITY_FACTOR, capacity / DEFAULT_CAPACITY))


def _length_hint(capacity: Optional[int]) -> str:
    """Prompt addendum telling the model how much room the overlay has."""
    factor = _capacity_factor(capacity)
    if factor >= 1.5:
        return (
            " The user has a large display: provide a well-developed answer - add useful "
            "detail, steps, or examples when relevant - while following the rules above."
        )
    if factor <= 0.75:
        return (
            " The display area is small: keep the answer as compact as possible "
            "while remaining complete."
        )
    return ""


# Unambiguous quiz wording. Deliberately narrow: generic "select one" also
# appears in essay prompts such as "Select one of the following topics...".
_MCQ_PHRASE_RE = re.compile(
    r"multiple[\s-]+choice"
    r"|choose\s+(the\s+)?(correct|best)\b"
    r"|select\s+(the\s+)?(correct|best)\b"
)

# Essay / long-answer instructions. These must be checked before option
# structure because essay prompts commonly use (a), (b), ... sub-questions.
_ESSAY_PATTERN_RE = re.compile(
    r"\bessay\b"
    r"|\blong[\s-]+answer\b"
    r"|\bdescriptive\b"
    r"|\bwrite\b.{0,40}\b(essay|paragraph|report|article|note)\b"
    r"|\bdiscuss\b"
    r"|\belaborate\b"
    r"|\bcompare\s+and\s+contrast\b"
    r"|\bcritically\s+(analy[sz]e|examine|evaluate)\b"
    r"|\b(explain|describe)\s+in\s+detail\b"
    r"|\bin\s+detail\b"
    r"|\b\d+\s*[-–]?\s*\d*\s*words\b"
    r"|\bword\s+limit\b"
    r"|\b\d+\s*marks\b"
    r"|\banswer\s+(the\s+following\s+)?(in|any)\b"
    r"|\bjustify\b"
    r"|\bsubstantiate\b"
    r"|\bevaluate\b"
)

# Lettered option on its own line: "A) text", "(b) text", "C. text", "d: text".
_MCQ_OPTION_LINE_RE = re.compile(r"(?m)^\s*[\(\[]?([a-dA-D])[\)\].:]\s+(\S.*)$")
# Same markers inline, e.g. "Which ...? A) 1 B) 2 C) 3 D) 4".
_MCQ_INLINE_OPTION_RE = re.compile(r"(?:^|[\s;])[\(\[]?([a-dA-D])[\)\].:]\s+\S")


def _count_mcq_options(content: str) -> int:
    """Count distinct lettered options that look like answer choices."""
    letters = set()
    for match in _MCQ_OPTION_LINE_RE.finditer(content):
        text = match.group(2).strip()
        if len(text) <= 80 and not text.endswith("?"):
            letters.add(match.group(1).lower())
    return len(letters)


def _count_inline_mcq_options(content: str) -> int:
    return len({m.group(1).lower() for m in _MCQ_INLINE_OPTION_RE.finditer(content)})


def _classify_screen_text(content: str) -> str:
    c = content.lower()

    # Unambiguous quiz wording wins over other cues.
    if _MCQ_PHRASE_RE.search(c):
        return "quiz_mcq"

    # Essay / long-answer prompts (checked before option structure so that
    # (a)/(b) sub-questions and topic lists are not treated as MCQ options).
    if _ESSAY_PATTERN_RE.search(c):
        return "essay"

    # Inline MCQ: explicit stem plus several option markers on the same line.
    if "which of the following" in c and _count_inline_mcq_options(c) >= 3:
        return "quiz_mcq"

    # Real option lists: at least two distinct short, non-question options.
    if _count_mcq_options(c) >= 2:
        return "quiz_mcq"

    # Coding detection
    if any(k in c for k in ["def ", "class ", "import ", "function", "```", "leetcode", "return ", "public static void"]):
        return "coding"

    # Question detection
    if "?" in content and len(content) < 4000:
        return "question"

    return "general"


_QUESTION_QUOTE_INSTRUCTION = (
    " First identify the actual question in the screen text, ignoring navigation, "
    "cookie banners, URLs, timestamps, and other page chrome. If there is a question, "
    "quote it in one short plain line starting exactly with 'Relevant question: ', "
    "then answer it."
)


def _screen_system_addon(kind: str) -> str:
    if kind == "quiz_mcq":
        return (
            _QUESTION_QUOTE_INSTRUCTION
            + " The user pasted screen text that looks like a quiz or multiple-choice question. "
            "If answer options are present, identify the best answer with a short justification "
            "and format your response as:\n"
            "**Answer:** [Option Letter/Number] Option Text\n"
            "**Explanation:** 1-2 concise sentences explaining why this is correct.\n"
            "If the text is not actually multiple-choice (for example an essay or long-answer "
            "question), ignore that format and answer the question directly and completely."
        )
    if kind == "essay":
        return (
            _QUESTION_QUOTE_INSTRUCTION
            + " The user pasted an essay or long-answer question from the screen. Answer it fully "
            "and directly: open with a clear answer or thesis, develop the key points in short "
            "paragraphs or bullet points, and end with a brief conclusion. Do not use "
            "multiple-choice formatting and do not comment on the question type - just answer it."
        )
    if kind == "coding":
        return (
            _QUESTION_QUOTE_INSTRUCTION
            + " The user pasted a coding problem or code from the screen. "
            "Give a correct, minimal solution or fix with code in a fenced block."
        )
    if kind == "question":
        return (
            _QUESTION_QUOTE_INSTRUCTION
            + " The user has a direct question in the screen text; answer it directly and completely."
        )
    return (
        _QUESTION_QUOTE_INSTRUCTION
        + " If the screen text contains a question or task, answer it directly. "
        "Otherwise, summarize the screen content as appropriate."
    )


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


def build_system_prompt(
    context_type: str,
    content: str,
    capacity: Optional[int] = None,
) -> str:
    if context_type == "manual":
        # Typed question (F-01): plain system prompt, no screen/meeting framing.
        return BASE_SYSTEM + _length_hint(capacity)
    if context_type == "meeting_audio":
        return _meeting_system_block() + _length_hint(capacity)
    if context_type == "meeting_question":
        # Strict 1-3 sentence format: never hint for longer answers.
        return _meeting_question_system_block()
    if context_type in ("lecture_notes", "lecture_audio"):
        return _lecture_system_block() + _length_hint(capacity)
    kind = _classify_screen_text(content)
    prompt = BASE_SYSTEM + _screen_system_addon(kind)
    if kind != "quiz_mcq":
        prompt += _length_hint(capacity)
    return prompt


def build_user_message(context_type: str, content: str) -> str:
    if context_type == "manual":
        return content
    if context_type in ("meeting_audio", "meeting_summary"):
        return f"Transcript (may be partial):\n\n{content}"
    if context_type == "meeting_question":
        return f"Live Question asked during meeting:\n\n{content}"
    if context_type in ("lecture_notes", "lecture_audio"):
        return f"Lecture audio transcript:\n\n{content}"
    return f"Screen OCR text:\n\n{content}"


def host_for_base_url(base_url: Optional[str] = None) -> str:
    """Return the lower-case host[:port] for a base URL ('' when invalid)."""
    raw = (base_url or DEFAULT_BASE_URL).strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    netloc = parsed.netloc or ""
    return netloc.rsplit("@", 1)[-1].lower()


def resolve_api_key(
    explicit: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """API key lookup for the provider selected by `base_url`.

    Order: explicit argument -> per-host keyring/plaintext store -> env/.env.
    The `.env` `GROQ_API_KEY` fallback only applies to the default Groq URL;
    custom providers must have their key saved in Settings.
    """
    load_dotenv()
    key = (explicit or "").strip()
    if not key:
        try:
            from utils.key_store import load_key_for

            key = load_key_for(host_for_base_url(base_url)).strip()
        except Exception as e:
            logger.warning("key_store load failed: %s", e)
    if not key and _is_default_provider(base_url):
        key = os.environ.get("GROQ_API_KEY", "").strip()
    return key


_NO_KEY_MSG = "No API key found. Open Settings -> API, paste your key, then Save."


def _host_for(base_url: Optional[str]) -> str:
    """Best-effort host label used in user-facing error messages."""
    raw = (base_url or DEFAULT_BASE_URL).strip()
    host = host_for_base_url(raw)
    return host or raw or "the provider"


def model_unavailable_message(model_id: str) -> str:
    return (
        f"Model '{model_id}' isn't available under this key — "
        "pick another model in Settings → API."
    )


def normalize_base_url(base_url: Optional[str] = None) -> str:
    """Return a validated base URL, defaulting to Groq.

    Most OpenAI-compatible providers require the `/v1` path. An invalid value
    raises a message the UI can show directly.
    """
    raw = (base_url or "").strip()
    if not raw:
        return DEFAULT_BASE_URL
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            f"Couldn't reach {raw} — check the Base URL "
            "(most providers need the /v1 path) and your connection."
        )
    return raw.rstrip("/")


def _is_default_provider(base_url: Optional[str]) -> bool:
    return (base_url or DEFAULT_BASE_URL).strip().rstrip("/") == DEFAULT_BASE_URL.rstrip("/")


def _models_to_try(
    model_id: Optional[str],
    base_url: Optional[str] = None,
) -> List[str]:
    """Primary model plus Groq backups only when using the default provider.

    Silent cross-provider fallback is a wrong-answer source, so a custom base
    URL always tries exactly the requested model.
    """
    primary = (model_id or MODEL_ID).strip() or MODEL_ID
    if not _is_default_provider(base_url):
        return [primary]
    return [primary] + [m for m in BACKUP_MODELS if m != primary]


def _status_code(err: Exception) -> Optional[int]:
    code = getattr(err, "status_code", None)
    if isinstance(code, int):
        return code
    response = getattr(err, "response", None)
    code = getattr(response, "status_code", None)
    if isinstance(code, int):
        return code
    match = re.search(r"\b([45]\d{2})\b", str(err))
    return int(match.group(1)) if match else None


def _is_auth_or_credit_error(err: Exception) -> bool:
    """True for failures that retrying or switching models cannot fix."""
    status = _status_code(err)
    if status in (401, 402, 403):
        return True
    text = str(err).lower()
    return any(
        marker in text
        for marker in (
            "invalid_api_key",
            "invalid api key",
            "unauthorized",
            "forbidden",
            "insufficient credits",
            "insufficient_quota",
        )
    )


def _looks_like_model_error(
    err: Exception,
    status: Optional[int],
) -> bool:
    text = str(err).lower()
    if any(
        marker in text
        for marker in (
            "model_not_found",
            "model not found",
            "model does not exist",
            "does not exist",
            "not have access",
            "invalid model",
            "no such model",
        )
    ):
        return True
    return status == 404 and "model" in text


def _classify_api_error(
    err: Exception,
    base_url: Optional[str] = None,
    model_id: Optional[str] = None,
) -> str:
    """Map a provider exception to a short, actionable user message."""
    host = _host_for(base_url)
    status = _status_code(err)
    text = str(err).lower()

    if status in (401, 403) or any(
        marker in text
        for marker in ("invalid_api_key", "invalid api key", "unauthorized", "forbidden")
    ):
        return (
            f"Your API key was rejected by {host} — paste it again "
            "from the provider's dashboard."
        )
    if status == 402 or "insufficient credits" in text or "insufficient_quota" in text:
        return f"This key has no credit left on {host} — top up or switch model."
    if status == 429 or "rate limit" in text:
        return f"Rate limit reached on {host} — wait a moment and try again."
    if _looks_like_model_error(err, status):
        model = (model_id or "").strip() or "that model"
        return model_unavailable_message(model)
    if status is not None and 500 <= status <= 599:
        return f"{host} had a server error — try again in a moment."
    if status == 404:
        return (
            f"Couldn't reach the API at {host} — check the Base URL "
            "(most providers need the /v1 path) and your connection."
        )
    if any(
        marker in text
        for marker in (
            "connection",
            "timed out",
            "timeout",
            "getaddrinfo",
            "unreachable",
            "failed to resolve",
            "name or service not known",
            "certificate",
            "ssl",
        )
    ):
        return (
            f"Couldn't reach {host} — check the Base URL "
            "(most providers need the /v1 path) and your connection."
        )
    return f"{host} error: {str(err)[:200]}"


def validate_key_and_model(
    api_key: Optional[str] = None,
    model_id: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[bool, str]:
    """Verify the API key works AND that `model_id` is available to it.

    Uses one cheap `models.list` call (no chat completion, no token usage).
    Returns (ok, human-readable message) — never raises.
    """
    load_dotenv()
    try:
        client = _get_client(base_url, api_key)
    except Exception as e:
        return False, str(e)
    try:
        models = client.models.list()
        ids = {m.id for m in (getattr(models, "data", None) or [])}
    except Exception as e:
        return False, _classify_api_error(e, base_url=base_url, model_id=model_id)
    model = (model_id or MODEL_ID).strip()
    if ids and model not in ids:
        return False, model_unavailable_message(model)
    return True, f"API key works - '{model}' is ready."


def _get_client(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """Build an OpenAI-compatible client for `base_url`.

    When no explicit key is given, the per-host store is consulted and the
    `.env` `GROQ_API_KEY` fallback is used only for the default Groq URL.
    """
    load_dotenv()
    if OpenAI is None:
        raise RuntimeError(
            "openai package is not installed.\n"
            "Install it with: pip install openai"
        )
    try:
        url = normalize_base_url(base_url)
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    key = (api_key or "").strip() or resolve_api_key(base_url=url)
    if not key:
        raise RuntimeError(_NO_KEY_MSG)
    return OpenAI(base_url=url, api_key=key)


def discover_models(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_id: Optional[str] = None,
) -> Tuple[bool, str, List[str]]:
    """Validate a base URL/key and return the provider's model IDs.

    Uses one `models.list` call (no chat completion, no token usage). When
    `model_id` is given and the provider returns a catalog, the model must be
    present. Returns `(ok, human-readable message, sorted model IDs)` and
    never raises.
    """
    load_dotenv()
    try:
        url = normalize_base_url(base_url)
    except ValueError as e:
        return False, str(e), []
    try:
        client = _get_client(url, api_key)
    except Exception as e:
        return False, str(e), []
    try:
        response = client.models.list()
    except Exception as e:
        return False, _classify_api_error(e, base_url=url, model_id=model_id), []

    ids = sorted(
        {
            str(getattr(model, "id", "")).strip()
            for model in (getattr(response, "data", None) or [])
            if str(getattr(model, "id", "")).strip()
        }
    )
    model = (model_id or "").strip()
    if ids and model and model not in ids:
        return False, model_unavailable_message(model), []
    host = _host_for(url)
    if not ids:
        return True, f"Connected to {host} — no models were returned.", []
    return True, f"Connected to {host} — {len(ids)} models available.", ids


def get_token_limit_for_context(
    context_type: str,
    content: str,
    capacity: Optional[int] = None,
) -> int:
    """Choose optimal max_tokens to minimize latency.

    `capacity` is the estimated visible tokens in the answer viewport; when
    given, the per-context base limit scales by 0.5x-2x with it.
    """
    if context_type == "meeting_question":
        base = 350
    else:
        kind = _classify_screen_text(content)
        if kind == "quiz_mcq":
            base = 450
        elif context_type in ("lecture_notes", "lecture_audio", "meeting_summary"):
            base = 1200
        else:
            base = MAX_TOKENS
    limit = int(base * _capacity_factor(capacity))
    return max(max(180, base // 2), min(2048, limit))


async def generate_answer(
    content: str,
    context_type: str = "screen",
    model_id: Optional[str] = None,
    capacity: Optional[int] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Async API call (non-streaming); used for tests or direct await."""
    client = _get_client(base_url, api_key)
    system = build_system_prompt(context_type, content, capacity)
    user_msg = build_user_message(context_type, content)
    max_tokens = get_token_limit_for_context(context_type, content, capacity)
    models_to_try = _models_to_try(model_id, base_url)
    last_err: Optional[Exception] = None

    for model in models_to_try:
        try:
            # to_thread forwards kwargs, so no closure over the loop var is needed.
            msg = await asyncio.to_thread(
                client.chat.completions.create,
                model=model,
                max_tokens=max_tokens,
                temperature=DETERMINISTIC_TEMPERATURE,
                seed=DETERMINISTIC_SEED,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
            )
            return (msg.choices[0].message.content or "").strip()
        except Exception as e:
            last_err = e
            if _looks_like_model_error(e, _status_code(e)):
                continue
            raise

    if last_err:
        raise last_err
    return ""


def _is_rate_limit_error(err: Exception) -> bool:
    """Return True if the exception looks like an HTTP 429 rate-limit error."""
    if RateLimitError is not None and isinstance(err, RateLimitError):
        return True
    if getattr(err, "status_code", None) == 429:
        return True
    response = getattr(err, "response", None)
    if getattr(response, "status_code", None) == 429:
        return True
    text = str(err).lower()
    return "429" in text or "rate limit" in text


MAX_MODEL_BACKOFF_SECONDS = 12.0


def _rate_limit_backoff(err: Exception, attempt: int) -> float:
    """Seconds to wait before retrying after a rate-limit error.

    Honors the server's Retry-After header when present; otherwise backs off
    exponentially (1s, 2s, 4s, ...). A single delay is capped at 30s; the
    worker additionally caps the total sleep per model (see
    `MAX_MODEL_BACKOFF_SECONDS`).
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
        capacity: Optional[int] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._content = content
        self._context_type = context_type
        self._model_id = (model_id or MODEL_ID).strip() or MODEL_ID
        self._capacity = capacity
        self._base_url = base_url
        self._api_key = api_key
        self._history = [
            dict(message) for message in (history or []) if isinstance(message, dict)
        ]

    def run(self) -> None:
        try:
            client = _get_client(self._base_url, self._api_key)
        except Exception as e:
            self.failed.emit(str(e))
            return

        system = build_system_prompt(self._context_type, self._content, self._capacity)
        user_msg = build_user_message(self._context_type, self._content)
        messages = [{"role": "system", "content": system}]
        for message in self._history:
            role = str(message.get("role", "")).strip()
            content = str(message.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_msg})
        max_tokens = get_token_limit_for_context(self._context_type, self._content, self._capacity)

        models_to_try = _models_to_try(self._model_id, self._base_url)
        last_err: Optional[Exception] = None

        for model in models_to_try:
            attempts = 0
            backoff_total = 0.0
            while attempts < 4:  # 1 initial + up to 3 rate-limit retries
                attempts += 1
                try:
                    stream = client.chat.completions.create(
                        model=model,
                        max_tokens=max_tokens,
                        temperature=DETERMINISTIC_TEMPERATURE,
                        seed=DETERMINISTIC_SEED,
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
                    logger.warning("AI stream with model %s failed (attempt %s): %s", model, attempts, e)
                    if _looks_like_model_error(e, _status_code(e)):
                        logger.warning("Model %s not found/accessible, trying next model...", model)
                        break
                    if _is_auth_or_credit_error(e):
                        # Retrying or trying backup models cannot fix a bad key
                        # or an empty balance; surface the message immediately.
                        self.failed.emit(
                            _classify_api_error(
                                e,
                                base_url=self._base_url,
                                model_id=model,
                            )
                        )
                        return
                    if _is_rate_limit_error(e):
                        if attempts > 3:
                            break  # give up on this model after the initial try + 3 retries
                        remaining = MAX_MODEL_BACKOFF_SECONDS - backoff_total
                        if remaining <= 0:
                            break
                        delay = min(_rate_limit_backoff(e, attempts), remaining)
                        backoff_total += delay
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
                            temperature=DETERMINISTIC_TEMPERATURE,
                            seed=DETERMINISTIC_SEED,
                            messages=messages,
                        )
                        body = (resp.choices[0].message.content or "").strip()
                        if body:
                            self.chunk_received.emit(body)
                        self.finished_ok.emit()
                        return
                    except Exception as e2:
                        last_err = e2
                        logger.warning("AI non-stream fallback with model %s failed: %s", model, e2)
                        if _looks_like_model_error(e2, _status_code(e2)):
                            break
                        if _is_auth_or_credit_error(e2):
                            self.failed.emit(
                                _classify_api_error(
                                    e2,
                                    base_url=self._base_url,
                                    model_id=model,
                                )
                            )
                            return
                        if _is_rate_limit_error(e2):
                            if attempts > 3:
                                break
                            remaining = MAX_MODEL_BACKOFF_SECONDS - backoff_total
                            if remaining <= 0:
                                break
                            delay = min(_rate_limit_backoff(e2, attempts), remaining)
                            backoff_total += delay
                            logger.warning(
                                "Rate limited (non-stream) on %s; retrying in %.1fs",
                                model,
                                delay,
                            )
                            if delay > 3:
                                self.chunk_received.emit("\n\n(rate limited, retrying...)\n\n")
                            time.sleep(delay)
                            continue
                    time.sleep(0.3 * attempts)

        if last_err:
            self.failed.emit(
                _classify_api_error(
                    last_err,
                    base_url=self._base_url,
                    model_id=self._model_id,
                )
            )
        else:
            self.failed.emit("Unknown API error")
