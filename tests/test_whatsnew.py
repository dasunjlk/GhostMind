"""Tests for utils/whatsnew.py — plain-language What's New extraction (C8).

The v1.0.1 and v1.0.0-rc1 bodies are the real release payloads from the
GitHub API (the same text the old "Open release page in browser" button
showed as raw JSON to the user).
"""
from __future__ import annotations

from utils.whatsnew import (
    MAX_BULLET_CHARS,
    MAX_BULLETS,
    extract_whatsnew,
)

# Real body of release v1.0.1 (api.github.com/repos/dasunjlk/GhostMind/releases).
V101_BODY = (
    "GhostMind v1.0.1 — a small patch focused on a smoother first run.\r\n"
    "\r\n"
    "### Fixed\r\n"
    "\r\n"
    "- Removed the startup \"No Groq API key found\" dependency warning. New users "
    "can now launch GhostMind and add their key whenever they are ready via "
    "**Settings → API**.\r\n"
    "\r\n"
    "### Install\r\n"
    "\r\n"
    "- **Installer:** `GhostMind-Setup-1.0.1.exe` — per-user install "
    "(`%LOCALAPPDATA%\\GhostMind`), no admin rights required.\r\n"
    "- **Portable:** `GhostMind-Portable-1.0.1.zip` — extract and run `ghostmind.exe`.\r\n"
    "- **Verify:** compare downloads against `SHA256SUMS.txt`.\r\n"
    "\r\n"
    "### Requirements\r\n"
    "\r\n"
    "- Windows 10/11 (x64)\r\n"
    "- Tesseract OCR installed separately (required for screen scanning)\r\n"
    "- A Groq API key — add it in **Settings → API** on first launch\r\n"
    "\r\n"
    "The installer is unsigned, so Windows SmartScreen may show a warning — choose "
    "**More info → Run anyway**.\r\n"
    "\r\n"
    "**Full changelog:** https://github.com/dasunjlk/GhostMind/compare/v1.0.0...v1.0.1\r\n"
)

# Real body of release v1.0.0-rc1 (auto-generated "What's Changed" PR list).
V100RC1_BODY = (
    "## What's Changed\r\n"
    "* Add GhostMind PyQt6 stealth overlay with OCR, Whisper, and Claude by "
    "@dasunjlk in https://github.com/dasunjlk/GhostMind/pull/1\r\n"
    "* Add system tray icon by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/2\r\n"
    "* add Transcript Export by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/3\r\n"
    "* Feat/bug fix by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/4\r\n"
    "* Audit and fix found errors by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/7\r\n"
    "* Add spec doc by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/8\r\n"
    "* Dev by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/10\r\n"
    "* implement log collection by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/11\r\n"
    "* Remove voice option and postponed it to future release by @dasunjlk in "
    "https://github.com/dasunjlk/GhostMind/pull/12\r\n"
    "* Fix screen click thought error by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/13\r\n"
    "* Make answer adapt to overlay size. (reflow + size aware length) by @dasunjlk in "
    "https://github.com/dasunjlk/GhostMind/pull/14\r\n"
    "* Feat/bug fix by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/15\r\n"
    "* Feat/header click through by @dasunjlk in https://github.com/dasunjlk/GhostMind/pull/16\r\n"
    "\r\n"
    "**Full Changelog**: https://github.com/dasunjlk/GhostMind/commits/v1.0.0-rc1\r\n"
)


class TestRealReleaseBodies:
    def test_v101_keeps_intro_and_fixed_section(self):
        bullets = extract_whatsnew(V101_BODY)

        assert bullets, "real v1.0.1 body must yield bullets"
        assert any(
            b.startswith("GhostMind v1.0.1 — a small patch") for b in bullets
        ), "the friendly intro summary is kept"
        assert any(
            "Removed the startup \"No Groq API key found\"" in b for b in bullets
        )

    def test_v101_drops_packaging_sections(self):
        lowered = "\n".join(extract_whatsnew(V101_BODY)).lower()

        assert "installer:" not in lowered
        assert "ghostmind-setup-1.0.1.exe" not in lowered
        assert "portable" not in lowered
        assert "sha256sums" not in lowered
        assert "windows 10/11" not in lowered
        assert "tesseract ocr installed separately" not in lowered
        assert "smartscreen" not in lowered
        assert "full changelog" not in lowered
        assert "compare/v1.0.0" not in lowered
        assert "###" not in lowered, "no raw markdown headings"

    def test_v101_fixed_bullet_is_markdown_stripped(self):
        bullets = extract_whatsnew(V101_BODY)

        fixed = [b for b in bullets if b.startswith("Removed the startup")]
        assert fixed, "the Fixed bullet survives"
        assert "**" not in fixed[0]
        # The full sentence exceeds the 120-char cap, so it is truncated
        # (…) — the tail ("Settings → API") is intentionally not shown.
        assert fixed[0].endswith("…")
        assert len(fixed[0]) == MAX_BULLET_CHARS

    def test_v100rc1_pr_list_is_cleaned(self):
        bullets = extract_whatsnew(V100RC1_BODY)

        assert "Add GhostMind PyQt6 stealth overlay with OCR, Whisper, and Claude" in bullets
        assert "Add system tray icon" in bullets
        # The 13-entry PR list is capped at MAX_BULLETS — later entries such
        # as "Remove voice option…" are intentionally not shown.
        assert len(bullets) == MAX_BULLETS

    def test_v100rc1_strips_pr_attribution_and_links(self):
        joined = "\n".join(extract_whatsnew(V100RC1_BODY))

        assert "@dasunjlk" not in joined
        assert "https://" not in joined
        assert "pull/" not in joined

    def test_v100rc1_is_capped_at_max_bullets(self):
        bullets = extract_whatsnew(V100RC1_BODY)

        assert len(bullets) == MAX_BULLETS


class TestSyntheticBodies:
    def test_markdown_syntax_stripped(self):
        body = (
            "### What's New\n"
            "- **Any AI provider**: add a Base URL and API key\n"
            "- `Steady answers`: same question, same answer\n"
            "- [Session memory](https://example.com) lasts while the app runs\n"
        )

        bullets = extract_whatsnew(body)

        assert bullets == [
            "Any AI provider: add a Base URL and API key",
            "Steady answers: same question, same answer",
            "Session memory lasts while the app runs",
        ]

    def test_unknown_sections_are_skipped(self):
        body = (
            "### What's New\n"
            "- Visible bullet\n"
            "### Internal Notes\n"
            "- Should not appear\n"
        )

        bullets = extract_whatsnew(body)

        assert bullets == ["Visible bullet"]

    def test_long_bullets_are_truncated(self):
        body = "### What's New\n- " + ("word " * 40).strip() + "\n"

        bullets = extract_whatsnew(body)

        assert len(bullets) == 1
        assert len(bullets[0]) == MAX_BULLET_CHARS
        assert bullets[0].endswith("…")

    def test_duplicate_lines_are_deduplicated(self):
        body = "### Fixed\n- Same bug fixed\n- Same bug fixed\n"

        assert extract_whatsnew(body) == ["Same bug fixed"]

    def test_numbered_bullets_are_supported(self):
        body = "### What's New\n1. First improvement\n2. Second improvement\n"

        assert extract_whatsnew(body) == [
            "First improvement",
            "Second improvement",
        ]


class TestFallbackAndSafety:
    def test_plain_text_body_uses_fallback(self):
        body = "\n".join(f"Plain sentence number {i}." for i in range(1, 7))

        bullets = extract_whatsnew(body)

        assert bullets == [
            "Plain sentence number 1.",
            "Plain sentence number 2.",
            "Plain sentence number 3.",
            "Plain sentence number 4.",
        ]

    def test_empty_body_yields_empty_list(self):
        assert extract_whatsnew("") == []

    def test_garbage_body_never_raises(self):
        assert isinstance(extract_whatsnew("###\n---\n***\n"), list)
        assert isinstance(extract_whatsnew("•••\n|||\n"), list)

    def test_whitespace_only_sections_fall_back_gracefully(self):
        body = "### Install\n\n### Requirements\n\n"

        assert extract_whatsnew(body) == []
