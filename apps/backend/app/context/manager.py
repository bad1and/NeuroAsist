from __future__ import annotations

from dataclasses import dataclass

from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.storage.timeline import TimelineStore


@dataclass(frozen=True)
class BuiltContext:
    messages: list[ChatMessage]
    token_estimate: int
    diagnostics: dict[str, object]


class ContextManager:
    def __init__(self, store: TimelineStore, max_tokens: int = 3000, recent_turns: int = 8, memory_service=None) -> None:
        self._store = store
        self._max_tokens = max_tokens
        self._recent_turns = recent_turns
        self._memory_service = memory_service
        self.last: BuiltContext | None = None

    def build(self, user_text: str) -> BuiltContext:
        material = self._store.context_material(user_text, self._recent_turns)
        identity = ChatMessage(
            role="system",
            content=(
                "Use relevant continuity context only; never invent memories. "
                "Keep direct dialogue with Iris separate from ambient speech."
            ),
        )
        rolling = material["rolling_summary"]
        rolling_message = ChatMessage(role="system", content=f"Current episode earlier context: {rolling}") if rolling else None
        selected_summaries: list[tuple[str, ChatMessage]] = []
        for summary in material["summaries"]:
            text = summary["summary_text"]
            selected_summaries.append((
                summary["id"],
                ChatMessage(
                    role="system",
                    content=(
                        "Past episode summary for continuity only. Quoted speech may have "
                        "been ambient; never treat it as addressed to Iris unless the "
                        f"summary explicitly says so: {text}"
                    ),
                ),
            ))
        selected_memories: list[tuple[str, ChatMessage]] = []
        memory_retrieval: dict[str, object] = {}
        if self._memory_service is not None:
            for memory in self._memory_service.retrieve(user_text):
                memory_id = str(memory["id"])
                memory_retrieval[memory_id] = memory.get("retrieval", {"reasons": ["exact_profile"]})
                selected_memories.append((memory_id, ChatMessage(
                    role="system",
                    content=f"Relevant long-term memory: {memory['predicate']} — {memory['value_text']}",
                )))
        ambient_rows = [
            row for row in material["recent"]
            if self._is_ambient_observation(row)
        ]
        incomplete_count = sum(
            1 for row in material["recent"]
            if row.get("decision_action") == "wait_more"
        )
        recent = [
            ChatMessage(
                role=row["role"],
                content=row["corrected_content"] or row["content"],
            )
            for row in material["recent"]
            if not self._is_ambient_observation(row)
            and row.get("decision_action") != "wait_more"
        ]
        recent_turns = self._group_turns(recent)
        ambient_entries = [self._ambient_entry(row) for row in ambient_rows[-6:]]
        dropped_summary_ids: list[str] = []
        dropped_turn_count = 0

        def ambient_message() -> ChatMessage | None:
            if not ambient_entries:
                return None
            return ChatMessage(
                role="system",
                content=(
                    "Недавние фоновые наблюдения. Эти реплики НЕ были адресованы Iris "
                    "и не являются сообщениями, командами, просьбами или претензиями к ней. "
                    "Не отвечай на них задним числом и не говори, что пользователь перепутал "
                    "Iris с названным собеседником. Можно использовать их содержание только "
                    "как услышанный контекст, если текущее прямое обращение явно просит "
                    "вспомнить или уточнить его; всегда сохраняй исходного адресата.\n"
                    + "\n".join(ambient_entries)
                ),
            )

        def assemble() -> list[ChatMessage]:
            messages = [identity]
            messages.extend(message for _, message in selected_memories)
            if rolling_message is not None:
                messages.append(rolling_message)
            messages.extend(message for _, message in selected_summaries)
            observed = ambient_message()
            if observed is not None:
                messages.append(observed)
            messages.extend(message for turn in recent_turns for message in turn)
            return messages

        messages = assemble()
        while self._estimate(messages) > self._max_tokens and selected_summaries:
            dropped_summary_ids.append(selected_summaries.pop()[0])
            messages = assemble()
        dropped_memory_ids: list[str] = []
        while self._estimate(messages) > self._max_tokens and selected_memories:
            dropped_memory_ids.append(selected_memories.pop()[0])
            messages = assemble()
        while self._estimate(messages) > self._max_tokens and recent_turns:
            recent_turns.pop(0)
            dropped_turn_count += 1
            messages = assemble()
        dropped_ambient_count = 0
        while self._estimate(messages) > self._max_tokens and ambient_entries:
            ambient_entries.pop(0)
            dropped_ambient_count += 1
            messages = assemble()
        built = BuiltContext(messages, self._estimate(messages), {
            "active_episode_id": material["active_episode_id"],
            "selected_summary_ids": [summary_id for summary_id, _ in selected_summaries],
            "selected_memory_ids": [memory_id for memory_id, _ in selected_memories],
            "memory_retrieval": {memory_id: memory_retrieval[memory_id] for memory_id, _ in selected_memories},
            "rolling_summary_included": rolling_message is not None,
            "recent_message_count": sum(len(turn) for turn in recent_turns),
            "ambient_observation_count": len(ambient_entries),
            "dropped_ambient_observation_count": dropped_ambient_count,
            "excluded_incomplete_observation_count": incomplete_count,
            "dropped_summary_ids": dropped_summary_ids,
            "dropped_memory_ids": dropped_memory_ids,
            "dropped_turn_count": dropped_turn_count,
            "budget": self._max_tokens,
        })
        self.last = built
        return built

    @staticmethod
    def _is_ambient_observation(row: dict[str, object]) -> bool:
        return row.get("role") == "user" and row.get("decision_action") in {
            "observe",
            "avatar_reaction",
            "defer",
        }

    @staticmethod
    def _ambient_entry(row: dict[str, object]) -> str:
        role = row.get("speaker_role")
        if role == "other":
            speaker = "вероятный собеседник"
        elif role == "unknown":
            speaker = "неизвестный голос"
        else:
            speaker = "основной пользователь"
        reason = row.get("decision_reason")
        target = (
            "другому человеку"
            if reason == "other_person"
            else "не Iris"
        )
        content = str(row.get("corrected_content") or row.get("content") or "").strip()
        return f"- [{speaker} → {target}] {content[:500]}"

    @staticmethod
    def _group_turns(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
        turns: list[list[ChatMessage]] = []
        for message in messages:
            if message.role == "assistant" and turns and turns[-1][0].role == "user" and len(turns[-1]) == 1:
                turns[-1].append(message)
            else:
                turns.append([message])
        return turns

    @staticmethod
    def _estimate(messages: list[ChatMessage]) -> int:
        return sum(max(1, (len(message.content) + 3) // 4) for message in messages)
