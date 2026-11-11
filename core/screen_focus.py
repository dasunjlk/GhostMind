"""
Isolate the actual question in OCR screen text.

OCR sees the whole page: navigation bars, cookie banners, URLs, timestamps,
copyright lines, and surrounding prose. The heuristics here remove that page
chrome and prefer the block that actually contains a question or an answer
group. They are deliberately conservative: when nothing looks like a question
the cleaned text is returned, and if cleaning removes everything the raw text
is returned unchanged so the answer feature never loses the screen.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_COOKIE_RE = re.compile(r"\bcookies?\b", re.IGNORECASE)
_SIGN_IN_RE = re.compile(
    r"\bsign[\s-]?in\b|\blog[\s-]?in\b|\blogin\b",
    re.IGNORECASE,
)
_SUBSCRIBE_RE = re.compile(r"\bsubscribe\b|\bnewsletter\b", re.IGNORECASE)
_COPYRIGHT_RE = re.compile(r"©|\bcopyright\b", re.IGNORECASE)
_UI_PHRASE_RE = re.compile(
    r"\b(?:accept all|reject all|manage preferences|privacy policy|"
    r"terms of service|skip to content|advertisement|sponsored)\b",
    re.IGNORECASE,
)
_MCQ_STEM_RE = re.compile(
    r"which\s+of\s+the\s+following"
    r"|multiple[\s-]+choice"
    r"|choose\s+(?:the\s+)?(?:correct|best)"
    r"|select\s+(?:the\s+)?(?:correct|best)",
    re.IGNORECASE,
)
_QUESTION_WORD_RE = re.compile(
    r"\b(?:what|why|how|when|where|who|which|whose|whom|define|explain|"
    r"calculate|solve|find|evaluate|describe|discuss|write|answer|state|"
    r"list|compare|identify)\b",
    re.IGNORECASE,
)
_OPTION_LINE_RE = re.compile(
    r"^\s*(?:[\(\[]?([a-dA-D])[\)\].:]|([0-9]{1,2})[\.\)])\s+(\S.*)$"
)
_INLINE_OPTION_RE = re.compile(r"(?:^|[\s;])[\(\[]?([a-dA-D])[\)\].:]\s+\S")
_TIME_RE = re.compile(
    r"^\s*(?:at\s+)?"
    r"(?:\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?|\d{1,2}\s*[ap]\.?m\.?)"
    r"\s*$",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"^\s*(?:"
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
    r"|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{2,4})?"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)[a-z]*\.?(?:,?\s*\d{2,4})?"
    r")\s*$",
    re.IGNORECASE,
)
_UI_WORDS = frozenset(
    {
        "accept",
        "account",
        "advertisement",
        "all",
        "back",
        "close",
        "content",
        "cookie",
        "cookies",
        "dashboard",
        "edit",
        "file",
        "follow",
        "footer",
        "header",
        "help",
        "home",
        "in",
        "login",
        "main",
        "manage",
        "menu",
        "more",
        "nav",
        "navigation",
        "next",
        "newsletter",
        "notifications",
        "open",
        "out",
        "preferences",
        "privacy",
        "profile",
        "reject",
        "search",
        "settings",
        "share",
        "sidebar",
        "sign",
        "signin",
        "skip",
        "sponsored",
        "subscribe",
        "terms",
        "to",
        "up",
        "view",
    }
)


def _is_short_junk(line: str) -> bool:
    return len(re.sub(r"\s+", "", line)) < 3


def _is_timestamp_or_date(line: str) -> bool:
    stripped = line.strip().strip("[]()")
    return bool(_TIME_RE.fullmatch(stripped) or _DATE_RE.fullmatch(stripped))


def _is_ui_noise(line: str) -> bool:
    """True for standalone menu words and menu-like lines."""
    normalized = re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()
    if not normalized:
        return True
    if normalized in _UI_WORDS:
        return True
    tokens = normalized.split()
    return bool(tokens) and all(token in _UI_WORDS for token in tokens)


def _has_chrome_token(line: str) -> bool:
    return bool(
        _COPYRIGHT_RE.search(line)
        or _COOKIE_RE.search(line)
        or _SIGN_IN_RE.search(line)
        or _SUBSCRIBE_RE.search(line)
        or _UI_PHRASE_RE.search(line)
        or _is_ui_noise(line)
    )


def _looks_like_real_question(line: str) -> bool:
    """Keep real questions without letting a stray OCR '?' keep a banner."""
    if _MCQ_STEM_RE.search(line):
        return True
    if "?" not in line:
        return False
    if _QUESTION_WORD_RE.search(line):
        return True
    words = re.findall(r"[A-Za-z0-9]+", line)
    if line.rstrip().endswith("?") and len(words) >= 3:
        return True
    # Short direct questions such as "Paris?" or "2+2?".
    return line.rstrip().endswith("?") and not _has_chrome_token(line)


def _looks_like_metadata(line: str) -> bool:
    """Catch OCR'd copyright/footer lines where © became a stray '?'."""
    if re.match(r"^\s*\?\s+\d", line):
        return True
    if re.match(r"^\s*\?\s+", line) and not _QUESTION_WORD_RE.search(line):
        return True
    has_year = re.search(r"\b(?:19|20)\d{2}\b", line) is not None
    has_time = re.search(r"\b\d{1,2}:\d{2}\b", line) is not None
    return has_year and has_time


def _clean_line(line: str) -> Optional[str]:
    """Return a cleaned line, an empty separator, or None when it is noise."""
    stripped = line.strip()
    if not stripped:
        return ""
    if _is_short_junk(stripped) or _is_timestamp_or_date(stripped):
        return None

    cleaned = _URL_RE.sub("", stripped)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -|·•")
    if not cleaned or _is_short_junk(cleaned):
        return None

    # Keep genuine questions even when they mention page-chrome words, e.g.
    # "What are cookies?" or "Why do I need to sign in?".
    if _looks_like_real_question(cleaned):
        return cleaned
    if _looks_like_metadata(cleaned) or _has_chrome_token(cleaned):
        return None
    return cleaned


def _collapse_blank_lines(lines: List[str]) -> List[str]:
    out: List[str] = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return out


def _block_ranges(lines: List[str]) -> List[Tuple[int, int]]:
    """Return (start, end) line ranges for non-empty paragraphs."""
    ranges: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for index, line in enumerate(lines):
        if line.strip():
            if start is None:
                start = index
        elif start is not None:
            ranges.append((start, index - 1))
            start = None
    if start is not None:
        ranges.append((start, len(lines) - 1))
    return ranges


def _count_option_lines(lines: List[str]) -> int:
    count = 0
    for line in lines:
        match = _OPTION_LINE_RE.match(line.strip())
        if not match:
            continue
        text = match.group(3).strip()
        if text and len(text) <= 120 and not text.endswith("?"):
            count += 1
    return count


def _count_inline_options(text: str) -> int:
    return len({match.group(1).lower() for match in _INLINE_OPTION_RE.finditer(text)})


def _looks_like_options(lines: List[str]) -> bool:
    text = "\n".join(lines)
    return _count_option_lines(lines) >= 2 or _count_inline_options(text) >= 3


def _looks_like_question(text: str) -> bool:
    return "?" in text or bool(_MCQ_STEM_RE.search(text))


def _score_block(lines: List[str]) -> int:
    text = "\n".join(lines)
    lower = text.lower()
    score = 0
    if "?" in text:
        score += 100
    if _MCQ_STEM_RE.search(lower):
        score += 90
    option_count = _count_option_lines(lines)
    if option_count >= 2:
        score += 60 + min(option_count, 4) * 5
    if _count_inline_options(text) >= 3:
        score += 60
    if _QUESTION_WORD_RE.search(lower):
        score += 20
    if len(text) > 1500:
        score -= 20
    return score


def _select_region(lines: List[str], ranges: List[Tuple[int, int]]) -> str:
    scored = [(_score_block(lines[start : end + 1]), index) for index, (start, end) in enumerate(ranges)]
    best_score, best_index = max(scored, key=lambda item: (item[0], -item[1]))
    if best_score <= 0:
        return "\n".join(lines).strip()

    start, end = ranges[best_index]
    chosen = lines[start : end + 1]

    # A question and its options are often separated by a blank line. Keep the
    # adjacent option block so the model sees every answer choice.
    if _looks_like_question("\n".join(chosen)) and best_index + 1 < len(ranges):
        next_start, next_end = ranges[best_index + 1]
        if _looks_like_options(lines[next_start : next_end + 1]):
            end = next_end
    if _looks_like_options(chosen) and best_index > 0:
        prev_start, prev_end = ranges[best_index - 1]
        if _looks_like_question("\n".join(lines[prev_start : prev_end + 1])):
            start = prev_start

    # Keep two lines of context around the winning region.
    start = max(0, start - 2)
    end = min(len(lines) - 1, end + 2)
    selected = "\n".join(lines[start : end + 1]).strip()
    return selected or "\n".join(lines).strip()


def isolate_screen_text(raw: str) -> str:
    """Return the question-bearing part of OCR text, never an empty string.

    Blank input stays blank; any other input that cleans down to nothing is
    returned unchanged (safe fallback).
    """
    if not raw:
        return ""
    try:
        cleaned_lines = _collapse_blank_lines(
            [cleaned for line in raw.splitlines() if (cleaned := _clean_line(line)) is not None]
        )
        cleaned = "\n".join(cleaned_lines).strip()
        if not cleaned:
            return raw.strip()
        ranges = _block_ranges(cleaned_lines)
        if not ranges:
            return cleaned
        return _select_region(cleaned_lines, ranges)
    except Exception:
        # This is an accuracy feature, not a reason to lose the screen.
        return raw.strip()
