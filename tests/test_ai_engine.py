"""Tests for core/ai_engine.py — prompt routing and text classification."""
from __future__ import annotations

import pytest

from core.ai_engine import (
    _classify_screen_text,
    _screen_system_addon,
    build_system_prompt,
    build_user_message,
)


class TestClassifyScreenText:
    def test_quiz_mcq_detection(self):
        assert _classify_screen_text("A) Python\nB) Java\nC) C++\nD) Ruby") == "quiz_mcq"

    def test_quiz_keywords(self):
        assert _classify_screen_text("Select one of the following multiple choice options") == "quiz_mcq"

    def test_coding_detection(self):
        assert _classify_screen_text("def hello():\n    print('hi')") == "coding"

    def test_coding_class(self):
        assert _classify_screen_text("class MyClass:\n    pass") == "coding"

    def test_coding_import(self):
        assert _classify_screen_text("import os\nimport sys") == "coding"

    def test_coding_function(self):
        assert _classify_screen_text("Write a function that sorts an array") == "coding"

    def test_coding_code_block(self):
        assert _classify_screen_text("```\nsome code\n```") == "coding"

    def test_question_detection(self):
        assert _classify_screen_text("What is the capital of France?") == "question"

    def test_general_fallback(self):
        assert _classify_screen_text("The quick brown fox jumps over the lazy dog") == "general"

    def test_long_content_not_question(self):
        long_text = "x" * 5000 + "?"
        assert _classify_screen_text(long_text) == "general"


class TestScreenSystemAddon:
    def test_quiz_addon(self):
        addon = _screen_system_addon("quiz_mcq")
        assert "quiz" in addon.lower() or "multiple-choice" in addon.lower()

    def test_coding_addon(self):
        addon = _screen_system_addon("coding")
        assert "coding" in addon.lower() or "code" in addon.lower()

    def test_question_addon(self):
        addon = _screen_system_addon("question")
        assert "question" in addon.lower()

    def test_general_addon(self):
        addon = _screen_system_addon("general")
        assert "summarize" in addon.lower() or "answer" in addon.lower()


class TestBuildSystemPrompt:
    def test_meeting_prompt(self):
        prompt = build_system_prompt("meeting_audio", "some transcript")
        assert "meeting" in prompt.lower() or "transcript" in prompt.lower()

    def test_screen_quiz_prompt(self):
        prompt = build_system_prompt("screen", "A) Yes\nB) No\nC) Maybe\nD) Never")
        assert "quiz" in prompt.lower() or "multiple-choice" in prompt.lower()

    def test_screen_coding_prompt(self):
        prompt = build_system_prompt("screen", "def sort(arr):\n    pass")
        assert "coding" in prompt.lower() or "code" in prompt.lower()

    def test_screen_general_prompt(self):
        prompt = build_system_prompt("screen", "The weather is nice today")
        assert "GhostMind" in prompt

    def test_prompt_contains_base_system(self):
        prompt = build_system_prompt("screen", "anything")
        assert "concise" in prompt.lower() or "clearly" in prompt.lower()


class TestBuildUserMessage:
    def test_meeting_message(self):
        msg = build_user_message("meeting_audio", "Hello everyone")
        assert "Transcript" in msg
        assert "Hello everyone" in msg

    def test_screen_message(self):
        msg = build_user_message("screen", "Some OCR text")
        assert "Screen" in msg or "OCR" in msg
        assert "Some OCR text" in msg
