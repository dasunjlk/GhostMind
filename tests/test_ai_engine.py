"""Tests for core/ai_engine.py — prompt routing and text classification."""
from __future__ import annotations

from core.ai_engine import (
    DEFAULT_CAPACITY,
    MAX_TOKENS,
    _classify_screen_text,
    _screen_system_addon,
    build_system_prompt,
    build_user_message,
    estimate_visible_tokens,
    get_token_limit_for_context,
)


class TestClassifyScreenText:
    def test_quiz_mcq_detection(self):
        assert _classify_screen_text("A) Python\nB) Java\nC) C++\nD) Ruby") == "quiz_mcq"

    def test_quiz_keywords(self):
        assert _classify_screen_text("Select one of the following multiple choice options") == "quiz_mcq"

    def test_inline_mcq_with_stem(self):
        text = "Which of the following is correct? A) 1 B) 2 C) 3 D) 4"
        assert _classify_screen_text(text) == "quiz_mcq"

    def test_essay_subquestions_not_mcq(self):
        text = (
            "Q1. Read the passage below and answer: "
            "(a) What is the author's main argument? (b) Do you agree? Justify."
        )
        assert _classify_screen_text(text) == "essay"

    def test_essay_topic_list_not_mcq(self):
        text = (
            "Select one of the following topics and write a 500-word essay: "
            "A. Climate change B. Digital privacy"
        )
        assert _classify_screen_text(text) == "essay"

    def test_essay_word_limit_not_mcq(self):
        text = "Answer the following in 200-250 words: Explain the water cycle."
        assert _classify_screen_text(text) == "essay"

    def test_essay_marks_prompt_not_mcq(self):
        text = "Discuss the impact of social media on society. (10 marks)"
        assert _classify_screen_text(text) == "essay"

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

    def test_quiz_addon_handles_non_mcq(self):
        addon = _screen_system_addon("quiz_mcq")
        assert "not actually multiple-choice" in addon.lower()

    def test_essay_addon(self):
        addon = _screen_system_addon("essay")
        assert "essay" in addon.lower() or "long-answer" in addon.lower()
        assert "**Answer:**" not in addon

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

    def test_screen_essay_prompt(self):
        prompt = build_system_prompt("screen", "Write an essay on climate change.")
        assert "essay" in prompt.lower()
        assert "**Answer:**" not in prompt

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

    def test_meeting_question_message(self):
        msg = build_user_message("meeting_question", "What is the sprint goal?")
        assert "Question" in msg
        assert "sprint goal" in msg

    def test_lecture_message(self):
        msg = build_user_message("lecture_notes", "Today we discuss neural nets")
        assert "Lecture" in msg
        assert "neural nets" in msg

    def test_screen_message(self):
        msg = build_user_message("screen", "Some OCR text")
        assert "Screen" in msg or "OCR" in msg
        assert "Some OCR text" in msg


class TestNewContextPrompts:
    def test_meeting_question_prompt(self):
        prompt = build_system_prompt("meeting_question", "Can someone explain this?")
        assert "meeting" in prompt.lower()
        assert "question" in prompt.lower()

    def test_lecture_prompt(self):
        prompt = build_system_prompt("lecture_notes", "Today we learn calculus")
        assert "lecture" in prompt.lower() or "class" in prompt.lower()


class TestTokenLimits:
    def test_meeting_question_limit(self):
        limit = get_token_limit_for_context("meeting_question", "test")
        assert limit <= 400

    def test_quiz_mcq_limit(self):
        limit = get_token_limit_for_context("screen", "A) one\nB) two")
        assert limit <= 500

    def test_essay_limit_not_quiz_capped(self):
        text = "Discuss the causes of the First World War. (10 marks)"
        assert get_token_limit_for_context("screen", text) == MAX_TOKENS


class TestEstimateVisibleTokens:
    def test_default_viewport_matches_default_capacity(self):
        # The answer viewport of the default 480x600 overlay measures 462x446.
        assert estimate_visible_tokens(462, 446, 13) == DEFAULT_CAPACITY

    def test_larger_viewport_means_more_capacity(self):
        small = estimate_visible_tokens(460, 450, 13)
        large = estimate_visible_tokens(900, 900, 13)
        assert large > small

    def test_smaller_font_fits_more(self):
        assert estimate_visible_tokens(462, 446, 10) > estimate_visible_tokens(462, 446, 20)

    def test_tiny_viewport_stays_positive(self):
        assert estimate_visible_tokens(1, 1, 13) > 0


class TestCapacityScaling:
    def test_no_capacity_keeps_base_limits(self):
        assert get_token_limit_for_context("screen", "hello", None) == MAX_TOKENS
        assert get_token_limit_for_context("meeting_question", "q?", None) == 350

    def test_default_capacity_keeps_base_limit(self):
        assert get_token_limit_for_context("screen", "hello", DEFAULT_CAPACITY) == MAX_TOKENS

    def test_larger_capacity_increases_limit(self):
        base = get_token_limit_for_context("screen", "hello")
        big = get_token_limit_for_context("screen", "hello", DEFAULT_CAPACITY * 4)
        assert big > base

    def test_smaller_capacity_decreases_limit(self):
        base = get_token_limit_for_context("screen", "hello")
        small = get_token_limit_for_context("screen", "hello", DEFAULT_CAPACITY // 4)
        assert small < base

    def test_limits_are_clamped(self):
        assert get_token_limit_for_context("meeting_question", "q?", 1) == 180
        assert get_token_limit_for_context("screen", "hello", 10**9) == 2048

    def test_quiz_limit_scales_with_capacity(self):
        assert get_token_limit_for_context("screen", "A) one\nB) two") == 450
        quarter = get_token_limit_for_context("screen", "A) one\nB) two", DEFAULT_CAPACITY // 4)
        assert quarter == 225


class TestLengthHints:
    def test_no_hint_without_capacity(self):
        prompt = build_system_prompt("screen", "The weather is nice today")
        assert "large display" not in prompt
        assert "display area is small" not in prompt

    def test_no_hint_at_default_capacity(self):
        prompt = build_system_prompt("screen", "The weather is nice today", DEFAULT_CAPACITY)
        assert "large display" not in prompt
        assert "display area is small" not in prompt

    def test_large_capacity_adds_detail_hint(self):
        prompt = build_system_prompt("screen", "The weather is nice today", DEFAULT_CAPACITY * 2)
        assert "large display" in prompt

    def test_small_capacity_adds_compact_hint(self):
        prompt = build_system_prompt("screen", "The weather is nice today", DEFAULT_CAPACITY // 4)
        assert "display area is small" in prompt

    def test_quiz_mcq_never_gets_hint(self):
        text = "A) Yes\nB) No\nC) Maybe\nD) Never"
        assert "large display" not in build_system_prompt("screen", text, DEFAULT_CAPACITY * 4)
        assert "display area is small" not in build_system_prompt(
            "screen", text, DEFAULT_CAPACITY // 4
        )

    def test_essay_gets_length_hint(self):
        prompt = build_system_prompt(
            "screen", "Write an essay on climate change.", DEFAULT_CAPACITY * 2
        )
        assert "large display" in prompt

    def test_meeting_question_never_gets_hint(self):
        prompt = build_system_prompt("meeting_question", "Can someone explain this?", DEFAULT_CAPACITY * 4)
        assert "large display" not in prompt

    def test_manual_gets_hint(self):
        prompt = build_system_prompt("manual", "What is 2+2?", DEFAULT_CAPACITY * 2)
        assert "large display" in prompt
