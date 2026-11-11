"""
In-session conversation memory.

The store lives entirely in RAM: closing GhostMind destroys it. Nothing in
this module opens, reads, or writes a file, so private conversation text is
never persisted to disk.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

MAX_EXCHANGES = 8
MAX_CHARS = 6000
# Meeting/lecture contexts are dormant in v1.1 and deliberately stay stateless.
MEMORY_CONTEXTS = frozenset({"manual", "screen"})


@dataclass
class _Exchange:
    question: str
    answer: str


class SessionMemory:
    """Completed question/answer pairs for the current app run."""

    def __init__(
        self,
        max_exchanges: int = MAX_EXCHANGES,
        max_chars: int = MAX_CHARS,
    ) -> None:
        self._max_exchanges = max(1, int(max_exchanges))
        self._max_chars = max(1, int(max_chars))
        self._exchanges: List[_Exchange] = []
        self._pending: Optional[str] = None

    def add_question(self, text: str, context_type: str = "manual") -> None:
        """Remember a question while its answer is being generated.

        The question becomes part of the history only when `add_answer()` is
        called; a failed request leaves no half-exchange behind.
        """
        question = (text or "").strip()
        if not question or context_type not in MEMORY_CONTEXTS:
            return
        self._pending = question

    def add_answer(self, text: str) -> None:
        """Complete the pending exchange; empty answers are discarded."""
        answer = (text or "").strip()
        question = self._pending
        self._pending = None
        if not answer or question is None:
            return
        self._exchanges.append(_Exchange(question=question, answer=answer))
        if len(self._exchanges) > self._max_exchanges:
            del self._exchanges[: -self._max_exchanges]

    def discard_pending(self) -> None:
        """Drop an unanswered question (request failed or was cleared)."""
        self._pending = None

    def clear(self) -> None:
        self._exchanges.clear()
        self._pending = None

    def is_empty(self) -> bool:
        return not self._exchanges and self._pending is None

    def window(self) -> List[Dict[str, str]]:
        """Return chat messages for the last exchanges, oldest first.

        At most `max_exchanges` pairs are returned and the combined content is
        kept near `max_chars`; the oldest pairs are dropped first.
        """
        exchanges = list(self._exchanges)
        while len(exchanges) > 1 and self._size(exchanges) > self._max_chars:
            exchanges.pop(0)
        if exchanges and self._size(exchanges) > self._max_chars:
            exchanges = [self._truncate(exchanges[0], self._max_chars)]

        messages: List[Dict[str, str]] = []
        for exchange in exchanges:
            if exchange.question:
                messages.append({"role": "user", "content": exchange.question})
            if exchange.answer:
                messages.append({"role": "assistant", "content": exchange.answer})
        return messages

    @staticmethod
    def _size(exchanges: List[_Exchange]) -> int:
        return sum(len(exchange.question) + len(exchange.answer) for exchange in exchanges)

    @staticmethod
    def _truncate(exchange: _Exchange, budget: int) -> _Exchange:
        """Fit one oversized exchange into the character budget."""
        answer = exchange.answer
        question = exchange.question
        if len(answer) >= budget:
            answer = _shorten(answer, budget)
            question = ""
        else:
            question = _shorten(question, budget - len(answer))
        return _Exchange(question=question, answer=answer)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"
