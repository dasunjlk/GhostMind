"""
Question detection helpers shared by the subtitle UI and the controller.

Moved here from ui/subtitle_bar.py so controller logic (main.py) does not
have to import from a UI module.
"""
from __future__ import annotations

import re

# Matches lines likely containing a question: wh-words, auxiliary/request
# phrases, and common follow-up prompts. Word-boundary anchored, case-insensitive.
QUESTION_RE = re.compile(
    r"(^|\b)(who|what|when|where|why|how|could you|can you|should we|is it|are we|"
    r"do you|did you|will you|would you|shall we|let me ask|tell me|explain|define|"
    r"which|whose|whom|how much|how many|how long|how far|how often|how old|"
    r"is there|are there|was there|were there|have you|has there|"
    r"can we|could we|should I|would it|do we|does it|"
    r"what about|what if|what's|what does|what do)\b",
    re.IGNORECASE,
)


def is_question(text: str) -> bool:
    """Return True if the text looks like a question ('?' or question keywords)."""
    return "?" in text or bool(QUESTION_RE.search(text))
