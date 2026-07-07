import json
from typing import Any

from apps.backend.app.agents.character.prompts import CHARACTER_SYSTEM_PROMPT
from apps.backend.app.llm.base import ChatMessage, LLMProvider
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory


class CharacterAgent:
    def __init__(
        self,
        llm_provider: LLMProvider,
        history: SQLiteMessageHistory,
        history_limit: int,
    ) -> None:
        self._llm_provider = llm_provider
        self._history = history
        self._history_limit = history_limit

    async def handle_user_message(self, session_id: str, user_text: str) -> dict[str, str]:
        context = self._history.get_recent_messages(session_id, limit=self._history_limit)
        messages = [
            ChatMessage(role="system", content=CHARACTER_SYSTEM_PROMPT),
            *context,
            ChatMessage(role="user", content=user_text),
        ]

        llm_response = await self._llm_provider.generate(messages)
        parsed = self._parse_response(llm_response.content)

        self._history.save_message(session_id, "user", user_text)
        self._history.save_message(session_id, "assistant", parsed["reply"])

        return parsed

    def _parse_response(self, raw_content: str) -> dict[str, str]:
        try:
            payload: Any = json.loads(raw_content)
        except json.JSONDecodeError:
            return {
                "reply": raw_content.strip(),
                "emotion": "neutral",
                "intent": "casual_chat",
            }

        if not isinstance(payload, dict):
            return {
                "reply": str(payload),
                "emotion": "neutral",
                "intent": "casual_chat",
            }

        reply = str(payload.get("reply") or "").strip()
        if not reply:
            reply = raw_content.strip()

        return {
            "reply": reply,
            "emotion": str(payload.get("emotion") or "neutral"),
            "intent": str(payload.get("intent") or "casual_chat"),
        }
