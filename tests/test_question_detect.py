"""Tests for core/question_detect.py — question regex coverage and helper."""
from __future__ import annotations

from core.question_detect import QUESTION_RE, is_question


class TestQuestionRegex:
    def test_wh_questions(self):
        for line in (
            "Who is the president?",
            "What is quicksort",
            "When was the second world war",
            "Where are the keys",
            "Why does it fail",
            "How does this work",
            "Which option is correct",
            "Whose turn is it",
            "Whom did you call",
        ):
            assert QUESTION_RE.search(line), line

    def test_request_phrases(self):
        for line in (
            "Can you explain this?",
            "Could you repeat that",
            "Should we deploy now",
            "Will you join the call",
            "Would you mind sharing",
            "Do you agree",
            "Did you see the error",
            "Shall we begin",
            "Let me ask you something",
            "Tell me about the plan",
            "Explain recursion",
            "Define entropy",
        ):
            assert QUESTION_RE.search(line), line

    def test_quantity_and_existence_phrases(self):
        for line in (
            "How much does it cost",
            "How many users joined",
            "How long will it take",
            "How far is the office",
            "How often do we sync",
            "How old is the framework",
            "Is there a backup?",
            "Are there alternatives",
            "Was there an outage",
            "Were there any issues",
            "Have you tried restarting",
            "Has there been any news",
        ):
            assert QUESTION_RE.search(line), line

    def test_group_and_followup_phrases(self):
        for line in (
            "Can we start now",
            "Could we try again",
            "Should I open a ticket",
            "Would it work offline",
            "Do we need approval",
            "Does it compile",
            "Is it finished",
            "Are we done",
            "What about the API",
            "What if it fails",
            "What's next",
            "What does this mean",
            "What do you think",
        ):
            assert QUESTION_RE.search(line), line

    def test_case_insensitive(self):
        assert QUESTION_RE.search("WHAT IS THE PLAN")

    def test_statements_do_not_match(self):
        for line in (
            "Sales increased this quarter",
            "The meeting starts at noon",
            "Please send the report tomorrow",
            "Great work everyone",
            "The build passed all checks",
        ):
            assert not QUESTION_RE.search(line), line


class TestIsQuestion:
    def test_question_mark_alone(self):
        assert is_question("is that right?")

    def test_keyword_without_question_mark(self):
        assert is_question("how does the deploy work")

    def test_plain_statement(self):
        assert not is_question("Sales increased this quarter")

    def test_case_insensitive(self):
        assert is_question("WHAT IS THIS")

    def test_empty_text(self):
        assert not is_question("")
