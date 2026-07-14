"""Small multilingual regression benchmark for deciding whether semantic mode may be enabled."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCase:
    query: str
    expected_id: str


MULTILINGUAL_CASES = (
    RetrievalCase("как меня зовут", "name"),
    RetrievalCase("I prefer concise answers", "concise"),
    RetrievalCase("мне нравятся короткие ответы", "concise"),
    RetrievalCase("what did we decide about chats", "continuous"),
)


def recall_at_one(results: dict[str, list[str]], cases: tuple[RetrievalCase, ...] = MULTILINGUAL_CASES) -> float:
    if not cases:
        return 0.0
    return sum(bool(results.get(case.query) and results[case.query][0] == case.expected_id) for case in cases) / len(cases)


def semantic_improves_eval(fts_results: dict[str, list[str]], hybrid_results: dict[str, list[str]]) -> bool:
    """A strict gate: ties do not enable the optional semantic path."""
    return recall_at_one(hybrid_results) > recall_at_one(fts_results)
