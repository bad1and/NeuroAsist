"""Canonical long-term-memory slot registry.

The extractor may use several natural predicate spellings, but policy and
retrieval operate on this small, versioned vocabulary.  Keeping cardinality,
temporal behaviour and search aliases together prevents one-off branches in
``MemoryService`` from silently disagreeing with each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class MemorySlotPolicy:
    cardinality: Literal["single", "multi"]
    temporal_semantics: Literal["atemporal", "current", "period"] = "atemporal"
    ttl_days: int | None = None
    search_aliases: str = ""


MEMORY_SLOT_POLICIES: dict[str, MemorySlotPolicy] = {
    "user.name": MemorySlotPolicy("single", search_aliases="имя пользователя user name кто я"),
    "assistant.developer": MemorySlotPolicy("multi", search_aliases="разработчик создатель developer creator Iris"),
    "assistant.developer_count": MemorySlotPolicy("single", search_aliases="число количество разработчиков developer count"),
    "user.likes_category": MemorySlotPolicy("multi", search_aliases="любимый жанр шутеры game genre likes"),
    "user.likes_game": MemorySlotPolicy("multi", search_aliases="любимая игра играет game plays likes"),
    "user.preference": MemorySlotPolicy("multi", search_aliases="предпочтение любит нравится preference likes"),
    "user.dislike": MemorySlotPolicy("multi", search_aliases="не любит ненавидит избегает dislike hates avoids"),
    "user.interest": MemorySlotPolicy("multi", search_aliases="интерес увлечение хобби interest hobby"),
    "user.habit": MemorySlotPolicy("multi", "period", 180, "привычка распорядок routine habit usually"),
    "user.note": MemorySlotPolicy("multi", search_aliases="явно запомнить заметка remember note"),
    "user.relationship.friend": MemorySlotPolicy("multi", search_aliases="друг друзья friend relationship"),
    "user.pet": MemorySlotPolicy("multi", search_aliases="питомец кот кошка собака pet cat dog"),
    "user.game_detail": MemorySlotPolicy("multi", search_aliases="детали игры особенности улучшения game features upgrades"),
    "user.current_mood": MemorySlotPolicy("single", "current", 1, "настроение mood сейчас"),
    "user.current_activity": MemorySlotPolicy("single", "current", 1, "занятие activity doing сейчас"),
    "user.current_goal": MemorySlotPolicy("single", "current", 30, "цель план goal objective сейчас"),
    "user.occupation": MemorySlotPolicy("single", "current", 365, "работа профессия occupation job works as"),
    "user.skill": MemorySlotPolicy("multi", search_aliases="навык умеет технология skill knows uses"),
    "user.learning": MemorySlotPolicy("multi", "current", 90, "учится изучает осваивает learning studying"),
    "user.project": MemorySlotPolicy("multi", "current", 120, "проект разрабатывает работает над project working on"),
    "user.location": MemorySlotPolicy("single", "current", 365, "город живет находится location lives city"),
    "user.prefers_response_length": MemorySlotPolicy("single", search_aliases="длина ответов короткие длинные response length"),
    "user.health_constraint": MemorySlotPolicy("multi", search_aliases="здоровье аллергия диагноз ограничение health allergy"),
    "user.constraint": MemorySlotPolicy("multi", search_aliases="ограничение constraint restriction"),
}


SINGLE_VALUE_MEMORY_SLOTS = frozenset(
    key for key, policy in MEMORY_SLOT_POLICIES.items() if policy.cardinality == "single"
)
KNOWN_MEMORY_SLOTS = frozenset(MEMORY_SLOT_POLICIES)
