"""Turn a GitHub release body into plain-language "What's New" bullets (C8).

Release bodies are written in markdown for the releases page. Inside the
update popup, raw markdown ("### Install", backticks, checksum instructions)
reads like noise to a normal user. This parser keeps the sections a user
cares about (What's New / Highlights / Fixed / Added / Changed and the intro
summary), strips markdown syntax, and caps the output so the popup stays
readable.

The parser is deliberately conservative and never raises: when nothing
parseable is found it falls back to the first few cleaned lines of the body.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

MAX_BULLETS = 6
MAX_BULLET_CHARS = 120
FALLBACK_LINES = 4

# Sections worth showing to a normal user (matched case-insensitively).
_SECTION_WHITELIST = frozenset(
    {
        "what's new",
        "whats new",
        "what's changed",
        "whats changed",
        "highlights",
        "fixed",
        "fixes",
        "added",
        "changed",
        "new",
        "improvements",
        "improved",
        "security",
    }
)

# Sections that are packaging/release metadata, not user-facing news.
_SECTION_BLACKLIST = frozenset(
    {
        "install",
        "installation",
        "installing",
        "requirements",
        "verify",
        "verification",
        "download",
        "downloads",
        "checksum",
        "checksums",
        "sha256",
        "changelog",
        "full changelog",
    }
)

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]*)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# "Add feature X by @user in https://github.com/.../pull/1" (PR-list bullets)
_PR_SUFFIX_RE = re.compile(r"\s+by\s+@\S+\s+in\s+\S+\s*$")
_URL_RE = re.compile(r"https?://\S+")
_FULL_CHANGELOG_RE = re.compile(
    r"^\s*(?:\*\*)?\s*full changelog(?:\*\*)?\s*:", re.IGNORECASE
)


def _normalize_section(name: str) -> str:
    return name.strip().rstrip(":").strip().lower()


def _clean_line(line: str) -> str:
    text = _BULLET_RE.sub("", line)
    text = _LINK_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(r"\1", text)
    text = _CODE_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = _PR_SUFFIX_RE.sub("", text)
    text = _FULL_CHANGELOG_RE.sub("", text)
    text = _URL_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" \t-–—•|")
    return text.strip()


def _truncate(text: str) -> str:
    if len(text) > MAX_BULLET_CHARS:
        return text[: MAX_BULLET_CHARS - 1].rstrip() + "…"
    return text


def _usable(text: str) -> bool:
    return bool(text) and len(text) >= 4


def _extract(body: str) -> List[str]:
    bullets: List[str] = []
    current_section: Optional[str] = None  # None = intro prose before any heading
    section_active = True  # intro prose is always kept (release summaries lead with it)
    saw_section = False

    for raw in body.splitlines():
        heading = _HEADING_RE.match(raw.strip())
        if heading:
            saw_section = True
            current_section = _normalize_section(heading.group(1))
            section_active = current_section in _SECTION_WHITELIST
            continue
        if not raw.strip() or not section_active:
            continue
        text = _clean_line(raw)
        if not _usable(text) or text in bullets:
            continue
        bullets.append(_truncate(text))

    if not saw_section:
        # No sections at all: treat the body as unstructured and keep only
        # the first few lines (the plan's fallback) instead of flooding.
        return _fallback(body)
    if not bullets:
        return _fallback(body)
    return bullets[:MAX_BULLETS]


def _fallback(body: str) -> List[str]:
    out: List[str] = []
    for raw in body.splitlines():
        if len(out) >= FALLBACK_LINES:
            break
        stripped = raw.strip()
        if not stripped or _HEADING_RE.match(stripped):
            continue
        text = _clean_line(stripped)
        if not _usable(text) or text in out:
            continue
        out.append(_truncate(text))
    return out


def extract_whatsnew(release_body: str) -> List[str]:
    """Plain-language bullet points from a GitHub release body.

    Keeps the user-facing sections and the intro summary, drops packaging
    metadata (Install / Requirements / Verify / checksums / changelog links),
    strips markdown, and caps the result at MAX_BULLETS bullets of at most
    MAX_BULLET_CHARS characters. Never raises: unparseable bodies fall back
    to their first few cleaned lines, and an empty body yields [].
    """
    if not release_body:
        return []
    try:
        return _extract(str(release_body))
    except Exception as e:  # pragma: no cover - defensive, never lose the popup
        logger.warning("What's New parse failed (%s); using raw fallback", e)
        try:
            return _fallback(str(release_body))
        except Exception:
            return []
