"""Conservative interpretation of small STT transcription mistakes."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceInputInterpretation:
    text: str
    replacement_count: int = 0

    @property
    def changed(self) -> bool:
        return self.replacement_count > 0


class VoiceInputInterpreter:
    """Correct only clear voice-transcription mistakes before LLM use.

    This is deliberately not a general spell checker.  It repairs a small set
    of common words and names already known to the companion.  Ambiguous words
    stay untouched so that the model can ask a clarifying question instead of
    silently inventing a fact.
    """

    _TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё'’-]*")
    _NAME_CONNECTORS = {"и", "and", "the", "a"}
    _COMMON_WORDS = (
        "привет", "здравствуй", "здравствуйте", "дела", "еда", "спасибо",
        "пожалуйста", "хорошо", "плохо", "хочу", "хочешь", "можешь",
        "помнишь", "зовут", "называется", "друг", "разработчик",
    )

    def __init__(self, memory_service=None) -> None:
        self._memory_service = memory_service

    def interpret(self, text: str, input_mode: str) -> VoiceInputInterpretation:
        if input_mode != "voice" or not text.strip():
            return VoiceInputInterpretation(text)
        common = {self._normalize(word): word for word in self._COMMON_WORDS}
        names = self._known_names()
        replacements = 0

        def replace(match: re.Match[str]) -> str:
            nonlocal replacements
            token = match.group(0)
            corrected = self._correct_token(token, names, common)
            if corrected == token:
                return token
            replacements += 1
            return corrected

        return VoiceInputInterpretation(self._TOKEN_RE.sub(replace, text), replacements)

    def _known_names(self) -> dict[str, str]:
        if self._memory_service is None:
            return {}
        try:
            memories = self._memory_service.store.list_memories(status="active", limit=250)
        except Exception:
            return {}
        names: dict[str, str] = {}
        for memory in memories:
            predicate = str(memory.get("predicate", ""))
            kind = str(memory.get("kind", ""))
            if predicate != "name" and predicate != "developers" and kind != "relationship":
                continue
            tokens = self._TOKEN_RE.findall(str(memory.get("value_text", "")))
            # Relationship values sometimes include a human-readable role,
            # e.g. "Рома — бывший одноклассник".  The leading name is useful
            # for STT correction; role words must not become correction targets.
            if kind == "relationship" and predicate != "developers":
                tokens = tokens[:1]
            for token in tokens:
                normalized = self._normalize(token)
                if len(normalized) < 3 or normalized in self._NAME_CONNECTORS:
                    continue
                names.setdefault(normalized, token)
        return names

    def _correct_token(self, token: str, names: dict[str, str], common: dict[str, str]) -> str:
        normalized = self._normalize(token)
        if len(normalized) < 3 or normalized in names or normalized in common:
            return token

        name_matches = self._matches(normalized, names, maximum_distance=2, allow_anagram=True)
        if len(name_matches) == 1:
            return name_matches[0]
        common_matches = self._matches(normalized, common, maximum_distance=1, allow_anagram=False)
        if len(common_matches) == 1:
            corrected = common_matches[0]
            return corrected.capitalize() if token[0].isupper() else corrected
        return token

    @classmethod
    def _matches(
        cls,
        token: str,
        candidates: dict[str, str],
        *,
        maximum_distance: int,
        allow_anagram: bool,
    ) -> list[str]:
        ranked: list[tuple[int, str]] = []
        for normalized, display in candidates.items():
            if allow_anagram and len(token) <= 7 and sorted(token) == sorted(normalized):
                ranked.append((0, display))
                continue
            distance = cls._edit_distance(token, normalized, maximum_distance)
            if distance <= maximum_distance:
                ranked.append((distance, display))
        if not ranked:
            return []
        best_distance = min(distance for distance, _ in ranked)
        return [display for distance, display in ranked if distance == best_distance]

    @staticmethod
    def _edit_distance(left: str, right: str, maximum: int) -> int:
        if abs(len(left) - len(right)) > maximum:
            return maximum + 1
        previous = list(range(len(right) + 1))
        for index, left_char in enumerate(left, start=1):
            current = [index]
            best = current[0]
            for right_index, right_char in enumerate(right, start=1):
                cost = 0 if left_char == right_char else 1
                value = min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + cost,
                )
                current.append(value)
                best = min(best, value)
            if best > maximum:
                return maximum + 1
            previous = current
        return previous[-1]

    @staticmethod
    def _normalize(value: str) -> str:
        return value.lower().replace("ё", "е")
