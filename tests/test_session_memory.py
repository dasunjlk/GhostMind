"""Tests for the in-session conversation memory (C3)."""
from __future__ import annotations

from pathlib import Path

import core.session_memory as session_memory
from core.session_memory import MAX_CHARS, MAX_EXCHANGES, SessionMemory


class TestWindow:
    def test_starts_empty(self):
        memory = SessionMemory()
        assert memory.is_empty() is True
        assert memory.window() == []

    def test_question_answer_pair_is_returned_oldest_first(self):
        memory = SessionMemory()
        memory.add_question("What is 2+2?", "manual")
        memory.add_answer("4")

        assert memory.is_empty() is False
        assert memory.window() == [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]

    def test_pending_question_is_not_injected_before_an_answer(self):
        memory = SessionMemory()
        memory.add_question("What is 2+2?", "manual")
        assert memory.window() == []

    def test_empty_answer_discards_the_pending_question(self):
        memory = SessionMemory()
        memory.add_question("What is 2+2?", "manual")
        memory.add_answer("   ")
        assert memory.is_empty() is True
        assert memory.window() == []

    def test_discard_pending_keeps_completed_exchanges(self):
        memory = SessionMemory()
        memory.add_question("first", "manual")
        memory.add_answer("one")
        memory.add_question("second", "manual")
        memory.discard_pending()

        assert memory.window() == [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "one"},
        ]

    def test_last_eight_exchanges_are_kept(self):
        memory = SessionMemory()
        for index in range(10):
            memory.add_question(f"q{index}", "manual")
            memory.add_answer(f"a{index}")

        window = memory.window()
        assert len(window) == MAX_EXCHANGES * 2
        assert window[0] == {"role": "user", "content": "q2"}
        assert window[-1] == {"role": "assistant", "content": "a9"}

    def test_char_cap_drops_the_oldest_exchanges(self):
        memory = SessionMemory()
        for index in range(8):
            memory.add_question(f"q{index}", "manual")
            memory.add_answer("a" * 1000)

        window = memory.window()
        total = sum(len(message["content"]) for message in window)
        assert total <= MAX_CHARS
        assert window[0] == {"role": "user", "content": "q3"}
        assert window[-1] == {"role": "assistant", "content": "a" * 1000}

    def test_single_oversized_exchange_is_truncated(self):
        memory = SessionMemory(max_chars=50)
        memory.add_question("q" * 100, "manual")
        memory.add_answer("a" * 100)

        window = memory.window()
        assert sum(len(message["content"]) for message in window) <= 50
        assert window[-1]["role"] == "assistant"

    def test_clear_forgets_everything(self):
        memory = SessionMemory()
        memory.add_question("q", "manual")
        memory.add_answer("a")
        memory.add_question("pending", "manual")

        memory.clear()

        assert memory.is_empty() is True
        assert memory.window() == []

    def test_meeting_contexts_are_not_remembered(self):
        memory = SessionMemory()
        memory.add_question("meeting transcript", "meeting_audio")
        memory.add_answer("answer")
        assert memory.is_empty() is True

        memory.add_question("lecture transcript", "lecture_notes")
        memory.add_answer("answer")
        assert memory.is_empty() is True

    def test_screen_scans_are_remembered(self):
        memory = SessionMemory()
        memory.add_question("OCR text", "screen")
        memory.add_answer("screen answer")

        assert memory.window() == [
            {"role": "user", "content": "OCR text"},
            {"role": "assistant", "content": "screen answer"},
        ]


class TestNoPersistence:
    def test_module_has_no_file_io_paths(self):
        source = Path(session_memory.__file__).read_text(encoding="utf-8")
        for token in (
            "open(",
            "Path(",
            "write_text",
            "read_text",
            "json",
            "toml",
            "pickle",
            "sqlite3",
        ):
            assert token not in source, f"session memory must not persist data ({token})"
