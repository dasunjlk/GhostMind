"""Tests for on-screen question isolation (C5).

OCR config decision: `TESSERACT_CONFIG = "--psm 6"` was evaluated but not
adopted. No QA screen corpus was available to show a measurable improvement
over Tesseract's default layout mode, so the default remains in place.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

import core.screen_reader as screen_reader
from core.ai_engine import _classify_screen_text
from core.screen_focus import isolate_screen_text
from core.screen_reader import ScreenScanWorker

NOISY_PAGE = """https://campus.example.edu/course/123
Home | Search | Menu
We use cookies to improve your experience. Accept all
© 2026 Example University
12:45 PM
Navigation
Chapter 4 Review
Which of the following is the capital of France?
A) Berlin
B) Madrid
C) Paris
D) Rome
Subscribe to our newsletter
"""


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestNoiseRemoval:
    def test_noisy_page_keeps_question_and_options(self):
        isolated = isolate_screen_text(NOISY_PAGE)

        assert "Which of the following is the capital of France?" in isolated
        for option in ("A) Berlin", "B) Madrid", "C) Paris", "D) Rome"):
            assert option in isolated

    def test_noisy_page_drops_page_chrome(self):
        isolated = isolate_screen_text(NOISY_PAGE)
        lowered = isolated.lower()

        assert "https://" not in lowered
        assert "cookie" not in lowered
        assert "©" not in isolated
        assert "12:45" not in isolated
        assert "subscribe" not in lowered
        assert "home | search | menu" not in lowered
        assert "navigation" not in lowered

    def test_standalone_ui_words_are_dropped(self):
        isolated = isolate_screen_text(
            "Home\nSearch\nMenu\nThe capital of France is Paris."
        )

        assert "The capital of France is Paris." in isolated
        assert "Home" not in isolated
        assert "Search" not in isolated
        assert "Menu" not in isolated

    def test_urls_are_stripped_but_surrounding_text_survives(self):
        isolated = isolate_screen_text(
            "Visit https://example.com/lesson for details\nWhat is 2+2?"
        )

        assert "https://" not in isolated
        assert "What is 2+2?" in isolated
        assert "Visit" in isolated

    def test_question_mentioning_chrome_words_survives(self):
        assert "What are cookies?" in isolate_screen_text("What are cookies?")
        assert "Why do I need to sign in?" in isolate_screen_text(
            "Why do I need to sign in?"
        )

    def test_lone_timestamps_and_dates_are_dropped(self):
        isolated = isolate_screen_text(
            "12:45 PM\n2026-11-05\nNov 5, 2026\nWhat is the deadline?"
        )

        assert "What is the deadline?" in isolated
        assert "12:45" not in isolated
        assert "2026-11-05" not in isolated
        assert "Nov 5, 2026" not in isolated

    def test_copyright_line_is_dropped(self):
        isolated = isolate_screen_text(
            "© 2026 Example University\nWhich planet is largest?"
        )

        assert "Which planet is largest?" in isolated
        assert "©" not in isolated
        assert "Example University" not in isolated

    def test_ocr_misread_copyright_as_stray_question_mark_is_dropped(self):
        isolated = isolate_screen_text(
            "? 2026 Example University 12:45 PM\nWhat is 2+2?"
        )

        assert "What is 2+2?" in isolated
        assert "2026" not in isolated
        assert "12:45" not in isolated

    def test_ocr_copyright_glued_to_subscribe_line_is_dropped(self):
        isolated = isolate_screen_text(
            "Subscribe to our newsletter ? 2026 Example University\n"
            "What is 2+2?"
        )

        assert "What is 2+2?" in isolated
        assert "subscribe" not in isolated.lower()
        assert "2026" not in isolated


class TestQuestionRegion:
    def test_question_block_wins_over_surrounding_prose(self):
        raw = (
            "Course dashboard\n"
            "Module 1\n"
            "Module 2\n"
            "Module 3\n"
            "\n"
            "Which of the following is a prime number?\n"
            "A) 4\n"
            "B) 6\n"
            "C) 7\n"
            "D) 8\n"
            "\n"
            "Next lesson\n"
            "Previous lesson\n"
            "Course footer\n"
        )

        isolated = isolate_screen_text(raw)

        assert "Which of the following is a prime number?" in isolated
        assert "C) 7" in isolated
        assert "Module 1" not in isolated
        assert "Course footer" not in isolated

    def test_mcq_options_in_a_separate_block_are_kept(self):
        raw = (
            "Which of the following is the largest planet?\n"
            "\n"
            "A) Earth\n"
            "B) Jupiter\n"
            "C) Mars\n"
            "D) Venus\n"
        )

        isolated = isolate_screen_text(raw)

        assert "Which of the following is the largest planet?" in isolated
        for option in ("A) Earth", "B) Jupiter", "C) Mars", "D) Venus"):
            assert option in isolated

    def test_no_question_falls_back_to_full_cleaned_text(self):
        raw = (
            "Home\n"
            "https://example.com\n"
            "The lecture covers the water cycle.\n"
            "It ends with evaporation and condensation.\n"
            "© 2026 Example\n"
        )

        isolated = isolate_screen_text(raw)

        assert "The lecture covers the water cycle." in isolated
        assert "It ends with evaporation and condensation." in isolated
        assert "https://" not in isolated
        assert "©" not in isolated

    def test_empty_input_stays_empty(self):
        assert isolate_screen_text("") == ""
        assert isolate_screen_text("   ") == ""

    def test_garbage_ocr_falls_back_to_raw(self):
        assert isolate_screen_text("|||") == "|||"
        assert isolate_screen_text("©\n12:34") == "©\n12:34"


class TestScreenScanWorker:
    def test_worker_isolates_ocr_and_preserves_window_header(
        self,
        qapp,
        monkeypatch,
    ):
        monkeypatch.setattr(
            screen_reader,
            "scan_and_extract",
            lambda monitor_id: NOISY_PAGE,
        )
        monkeypatch.setattr(
            screen_reader,
            "get_active_window_title",
            lambda: "Campus Portal",
        )
        monkeypatch.setattr(screen_reader, "detect_meeting_app", lambda: None)

        worker = ScreenScanWorker(1)
        outputs: list[str] = []
        details: list[dict] = []
        worker.finished_ok.connect(outputs.append)
        worker.finished_details.connect(details.append)
        worker.run()

        assert len(outputs) == 1
        assert outputs[0].startswith("[Active Window: Campus Portal]\n\n")
        assert "Which of the following is the capital of France?" in outputs[0]
        assert "https://" not in outputs[0]
        assert "cookies" not in outputs[0].lower()
        assert details[0]["ocr_text"] == NOISY_PAGE
        assert details[0]["isolated_text"] == isolate_screen_text(NOISY_PAGE)
        assert details[0]["combined_text"] == outputs[0]

    def test_worker_preserves_meeting_app_in_header(self, qapp, monkeypatch):
        monkeypatch.setattr(
            screen_reader,
            "scan_and_extract",
            lambda monitor_id: "What is the agenda?",
        )
        monkeypatch.setattr(
            screen_reader,
            "get_active_window_title",
            lambda: "Weekly Sync",
        )
        monkeypatch.setattr(screen_reader, "detect_meeting_app", lambda: "Zoom")

        worker = ScreenScanWorker(1)
        outputs: list[str] = []
        worker.finished_ok.connect(outputs.append)
        worker.run()

        assert outputs[0].startswith(
            "[Active Window: Weekly Sync] [Meeting App: Zoom]\n\n"
        )

    def test_classification_runs_on_the_isolated_text(self, qapp, monkeypatch):
        monkeypatch.setattr(
            screen_reader,
            "scan_and_extract",
            lambda monitor_id: NOISY_PAGE,
        )
        monkeypatch.setattr(
            screen_reader,
            "get_active_window_title",
            lambda: "Campus Portal",
        )
        monkeypatch.setattr(screen_reader, "detect_meeting_app", lambda: None)

        worker = ScreenScanWorker(1)
        details: list[dict] = []
        worker.finished_details.connect(details.append)
        worker.run()

        assert _classify_screen_text(details[0]["combined_text"]) == "quiz_mcq"
