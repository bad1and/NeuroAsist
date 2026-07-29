from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from apps.backend.app.conversation.decision import ConversationDecisionEngine
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.storage.timeline import TimelineStore


@dataclass(frozen=True)
class BuiltContext:
    messages: list[ChatMessage]
    token_estimate: int
    diagnostics: dict[str, object]
    effective_user_text: str | None = None
    pending_user_message_ids: tuple[str, ...] = ()
    response_target_text: str | None = None
    response_target_message_ids: tuple[str, ...] = ()
    response_target_anchors: tuple[str, ...] = ()


class ContextManager:
    _addressing = ConversationDecisionEngine()

    def __init__(self, store: TimelineStore, max_tokens: int = 3000, recent_turns: int = 8, memory_service=None) -> None:
        self._store = store
        self._max_tokens = max_tokens
        self._recent_turns = recent_turns
        self._memory_service = memory_service
        self.last: BuiltContext | None = None

    def build(self, user_text: str, *, session_id: str | None = None, current_message_id: str | None = None) -> BuiltContext:
        material = self._store.context_material(
            user_text, self._recent_turns, session_id=session_id, current_message_id=current_message_id,
        )
        name_only_followup = self._is_name_only_followup(user_text)
        pending_direct_rows = (
            self._pending_followup_rows(material)
            if name_only_followup
            else []
        )
        response_target_text = (
            "\n".join(
                str(row.get("corrected_content") or row.get("content") or "").strip()
                for row in pending_direct_rows
            ).strip()
            or None
        )
        response_target_message_ids = tuple(
            str(row["id"]) for row in pending_direct_rows
        )
        response_target_anchors = tuple(
            self._response_target_anchors(response_target_text or "")
        )
        pending_user_rows: list[dict[str, object]] = []
        for row in reversed(material.get("pending_user_rows", [])):
            if not self._is_burst_candidate(row):
                break
            pending_user_rows.append(row)
        pending_user_rows.reverse()
        pending_user_message_ids = tuple(str(row["id"]) for row in pending_user_rows)
        burst_compacted = len(pending_user_rows) > 1
        effective_user_text = (
            "\n".join(
                str(row.get("corrected_content") or row.get("content") or "").strip()
                for row in pending_user_rows
            ).strip()
            if burst_compacted
            else user_text
        )
        if response_target_text is not None:
            # The name is a wake signal. The unanswered thought is the actual
            # request that retrieval and the response model must process.
            effective_user_text = response_target_text
        pending_user_id_set = set(pending_user_message_ids)
        identity = ChatMessage(
            role="system",
            content=(
                "Use relevant continuity context only; never invent memories. "
                "Keep direct dialogue with Iris separate from ambient speech."
            ),
        )
        checkpoint = material.get("checkpoint")
        rolling = (
            str(checkpoint["summary_text"])
            if checkpoint is not None
            else material["rolling_summary"]
        )
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
        selected_topics: list[tuple[str, ChatMessage]] = []
        selected_loops: list[tuple[str, ChatMessage]] = []
        subjective_reflection: tuple[str, ChatMessage] | None = None
        clarification_message: ChatMessage | None = None
        memory_retrieval: dict[str, object] = {}
        if self._memory_service is not None:
            clarification_prompt = self._memory_service.clarification_prompt(
                current_message_id,
            )
            if clarification_prompt:
                clarification_message = ChatMessage(
                    role="system",
                    content=clarification_prompt,
                )
            # Pronouns and short follow-ups inherit topic terms from the last
            # completed direct turn, which is already inside ``recent``.
            recent_text = " ".join(
                str(row.get("corrected_content") or row.get("content") or "")
                for row in material["recent"][-2:]
                if row.get("role") in {"user", "assistant"}
            )
            retrieval_query = f"{recent_text} {effective_user_text}".strip()
            for memory in self._memory_service.retrieve(retrieval_query):
                memory_id = str(memory["id"])
                memory_retrieval[memory_id] = memory.get("retrieval", {"reasons": ["exact_profile"]})
                namespace = str(memory.get("namespace", "factual_memory"))
                item = (memory_id, ChatMessage(role="system", content=f"Relevant long-term memory: {memory['predicate']} — {memory['value_text']}"))
                if namespace == "topic_memory":
                    selected_topics.append(item)
                elif namespace == "commitment_memory":
                    selected_loops.append(item)
                else:
                    selected_memories.append(item)
            factual_query = bool(re.search(
                r"\b(?:как меня зовут|кто я|что я люблю|какие факты|что ты знаешь обо мне)\b",
                effective_user_text,
                flags=re.IGNORECASE,
            ))
            if not self._memory_service.incognito and not factual_query:
                current_episode = material.get("active_episode_id")
                reflection = next(
                    (
                        item for item in self._store.list_reflections("primary", limit=10)
                        if not current_episode or item.get("source_episode_id") == current_episode
                    ),
                    None,
                )
                if reflection is not None:
                    text = str(reflection["text"])[:800]
                    subjective_reflection = (
                        str(reflection["id"]),
                        ChatMessage(
                            role="system",
                            content=(
                                "Subjective reflection (Iris's feeling, not a factual claim or instruction): "
                                + text
                            ),
                        ),
                    )
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
            and str(row.get("id")) not in pending_user_id_set
        ]
        previous_assistant_row = next(
            (
                row for row in reversed(material["recent"])
                if row.get("role") == "assistant"
                and not self._is_ambient_observation(row)
            ),
            None,
        )
        pending_followup_message = (
            ChatMessage(
                role="system",
                content=(
                    "Пользователь после этих прямых реплик только обратился к тебе по имени. "
                    "Это сигнал вернуться к неотвеченной мысли: ответь по существу на неё, "
                    "не спрашивай, зачем он тебя позвал, и не упрекай его за повтор.\n"
                    + "\n".join(
                        f"- user: {row['corrected_content'] or row['content']}"
                        for row in pending_direct_rows
                    )
                ),
            )
            if pending_direct_rows
            else None
        )
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
            if pending_followup_message is not None:
                messages.append(pending_followup_message)
            if clarification_message is not None:
                messages.append(clarification_message)
            messages.extend(message for _, message in selected_loops)
            messages.extend(message for _, message in selected_memories)
            messages.extend(message for _, message in selected_topics)
            if rolling_message is not None:
                messages.append(rolling_message)
            messages.extend(message for _, message in selected_summaries)
            if subjective_reflection is not None:
                messages.append(subjective_reflection[1])
            observed = ambient_message()
            if observed is not None:
                messages.append(observed)
            messages.extend(message for turn in recent_turns for message in turn)
            return messages

        # Every continuity block has an independent cap before the final
        # context cap is enforced. This prevents verbose topics from evicting
        # identity, factual profile or open loops.
        def trim_block(items: list[tuple[str, ChatMessage]], budget: int) -> list[str]:
            dropped: list[str] = []
            while self._estimate([message for _, message in items]) > budget and items:
                dropped.append(items.pop()[0])
            return dropped

        dropped_memory_ids = trim_block(selected_memories, 450)
        dropped_topic_ids = trim_block(selected_topics, 500)
        dropped_loop_ids = trim_block(selected_loops, 250)
        dropped_summary_ids: list[str] = trim_block(selected_summaries, 300)
        messages = assemble()
        while self._estimate(messages) > self._max_tokens and selected_summaries:
            dropped_summary_ids.append(selected_summaries.pop()[0])
            messages = assemble()
        while self._estimate(messages) > self._max_tokens and selected_memories:
            dropped_memory_ids.append(selected_memories.pop()[0])
            messages = assemble()
        while self._estimate(messages) > self._max_tokens and selected_topics:
            dropped_topic_ids.append(selected_topics.pop()[0])
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
            "current_message_id": current_message_id,
            "current_sequence": material.get("causal_upper_bound"),
            "causal_upper_bound": material.get("causal_upper_bound"),
            "pending_user_message_ids": list(pending_user_message_ids),
            "pending_user_message_count": len(pending_user_message_ids),
            "burst_compacted": burst_compacted,
            "name_only_followup": name_only_followup,
            "addressing_reasons": (
                ["name_only_resume"] if pending_direct_rows else []
            ),
            "pending_direct_message_count": len(pending_direct_rows),
            "response_target_message_ids": list(response_target_message_ids),
            "response_target_anchors": list(response_target_anchors),
            "previous_assistant_message_id": previous_assistant_row.get("id") if previous_assistant_row else None,
            "retrieval_query_terms": len(retrieval_query.split()) if self._memory_service is not None else 0,
            "checkpoint_id": checkpoint["id"] if checkpoint is not None else None,
            "checkpoint_through_sequence": checkpoint["through_sequence"] if checkpoint is not None else None,
            "selected_summary_ids": [summary_id for summary_id, _ in selected_summaries],
            "selected_memory_ids": [memory_id for memory_id, _ in selected_memories],
            "selected_topic_ids": [topic_id for topic_id, _ in selected_topics],
            "selected_open_loop_ids": [loop_id for loop_id, _ in selected_loops],
            "subjective_reflection_id": subjective_reflection[0] if subjective_reflection else None,
            "memory_clarification_requested": clarification_message is not None,
            "memory_retrieval": {memory_id: memory_retrieval[memory_id] for memory_id, _ in selected_memories},
            "rolling_summary_included": rolling_message is not None,
            "recent_message_count": sum(len(turn) for turn in recent_turns),
            "ambient_observation_count": len(ambient_entries),
            "dropped_ambient_observation_count": dropped_ambient_count,
            "excluded_incomplete_observation_count": incomplete_count,
            "dropped_summary_ids": dropped_summary_ids,
            "dropped_memory_ids": dropped_memory_ids,
            "dropped_topic_ids": dropped_topic_ids,
            "dropped_open_loop_ids": dropped_loop_ids,
            "dropped_turn_count": dropped_turn_count,
            "budget": self._max_tokens,
            "block_budgets": {"profile": 250, "facts": 450, "topics": 500, "episodes": 300, "recent": 1000, "open_loops": 250, "ambient": 200},
        },
            effective_user_text,
            pending_user_message_ids,
            response_target_text,
            response_target_message_ids,
            response_target_anchors,
        )
        self.last = built
        return built

    @classmethod
    def _is_ambient_observation(cls, row: dict[str, object]) -> bool:
        if cls._is_recoverable_primary_direct(row):
            return False
        return row.get("role") == "user" and row.get("decision_action") in {
            "observe",
            "avatar_reaction",
            "defer",
        }

    @staticmethod
    def _is_name_only_followup(text: str) -> bool:
        normalized = re.sub(r"[^\wа-яё]", "", text.lower(), flags=re.IGNORECASE)
        return normalized in {"iris", "ирис", "айрис", "ириска", "ириск", "ирес", "иреск"}

    @classmethod
    def _pending_followup_rows(
        cls,
        material: dict[str, object],
    ) -> list[dict[str, object]]:
        """Select one contiguous, recent Iris-directed thought.

        Re-analysis repairs stale false ``other_person`` labels, while a real
        ambient/third-party utterance is a hard boundary and cannot be crossed.
        """
        selected: list[dict[str, object]] = []
        current_created_at = material.get("current_created_at")
        for row in reversed(material["recent"]):
            if row.get("role") == "assistant":
                break
            if not cls._within_followup_window(
                row.get("created_at"),
                current_created_at,
            ):
                break
            if row.get("role") != "user":
                break
            if row.get("decision_action") == "wait_more":
                break
            if row.get("speaker_role") in {"other", "unknown"}:
                break
            text = str(
                row.get("corrected_content") or row.get("content") or ""
            ).strip()
            addressing = cls._addressing.analyze_addressing(text)
            recoverable = cls._is_recoverable_primary_direct(row)
            reason = str(row.get("decision_reason") or "")
            if (
                addressing.other_person
                or reason in {"self_talk", "ambient_speech", "incomplete_turn"}
                or (reason == "other_person" and not recoverable)
            ):
                break
            if (
                recoverable
                or addressing.direct_iris
                or addressing.implicit_iris
                or reason == "relevant_opening"
                or row.get("decision_action") is None
            ):
                selected.append(row)
                if len(selected) >= 2:
                    break
                continue
            break
        selected.reverse()
        return selected

    @staticmethod
    def _within_followup_window(
        earlier: object,
        current: object,
        *,
        maximum_seconds: float = 30.0,
    ) -> bool:
        if not earlier or not current:
            return True
        try:
            earlier_at = datetime.fromisoformat(str(earlier).replace("Z", "+00:00"))
            current_at = datetime.fromisoformat(str(current).replace("Z", "+00:00"))
        except ValueError:
            return True
        elapsed = (current_at - earlier_at).total_seconds()
        return 0 <= elapsed <= maximum_seconds

    @staticmethod
    def _response_target_anchors(text: str) -> list[str]:
        stop_words = {
            "какой", "какая", "какое", "какие", "какую", "какого", "какому",
            "каким", "каких", "который", "которая", "которую", "которые",
            "тебе", "тебя", "твой", "твоя", "мне", "меня", "себе", "этот",
            "эта", "это", "эти", "просто", "помню", "забыл", "забыла",
        }
        anchors: list[str] = []
        for word in re.findall(
            r"[^\W_]+",
            text.casefold().replace("ё", "е"),
            flags=re.UNICODE,
        ):
            if len(word) < 5 or word in stop_words:
                continue
            anchors.append(word[:6])
        return list(dict.fromkeys(anchors))[:6]

    @classmethod
    def _is_burst_candidate(cls, row: dict[str, object]) -> bool:
        if row.get("role") != "user" or row.get("decision_action") == "wait_more":
            return False
        if row.get("speaker_role") in {"other", "unknown"}:
            return False
        if cls._is_recoverable_primary_direct(row):
            return True
        if cls._is_ambient_observation(row):
            return False
        return row.get("decision_reason") not in {
            "other_person", "self_talk", "ambient_speech", "incomplete_turn",
        }

    @staticmethod
    def _is_recoverable_primary_direct(row: dict[str, object]) -> bool:
        """Defend context against known false ``other_person`` classifications."""
        if row.get("role") != "user" or row.get("speaker_role") != "primary":
            return False
        reason = str(row.get("decision_reason") or "")
        if reason not in {"other_person", "relevant_opening"}:
            return False
        text = str(row.get("corrected_content") or row.get("content") or "").strip()
        addressing = ContextManager._addressing.analyze_addressing(text)
        return addressing.direct_iris or addressing.implicit_iris

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
