from __future__ import annotations

import asyncio
import re

from apps.backend.app.coding.service import CodingAgentService


class CodingBridge:
    """Narrow orchestration bridge owned by the main Character Agent.

    It deliberately does not expose filesystem or command tools to the
    conversational model. The main agent only creates, steers, cancels and
    reports durable Coding Agent tasks.
    """

    _code_signal = re.compile(
        r"(?:coding\s*agent|агент[ау]?\s+код|код(?:е|овый|инг)?|программ|"
        r"репозитор|файл(?:ы|а)?|тест(?:ы|ировать)?|bug|баг|ошибк|"
        r"python|typescript|javascript|react|backend|frontend|api|refactor|рефактор)",
        re.IGNORECASE,
    )
    _action_signal = re.compile(
        r"(?:сделай|реализуй|исправь|измени|добавь|создай|напиши|проверь|запусти|"
        r"fix|implement|change|add|create|write|test|run)", re.IGNORECASE,
    )
    _stop_signal = re.compile(r"(?:останови|стоп|отмени|прекрати|cancel|stop)", re.IGNORECASE)
    _status_signal = re.compile(r"(?:статус|что\s+дела|прогресс|status|progress)", re.IGNORECASE)
    _instruction_signal = re.compile(r"(?:дополн|уточн|также|instead|ещ[её])", re.IGNORECASE)

    def __init__(self, service: CodingAgentService) -> None:
        self.service = service

    def observe_user_message(self, session_id: str, user_text: str, source_message=None) -> str | None:
        if not self.service.enabled:
            return None
        tasks = self.service.store.list_coding_tasks(limit=30) if self.service.store is not None else []
        active = next((item for item in tasks if item["status"] in {"pending", "running", "waiting_for_input"}), None)
        source_message_id = getattr(source_message, "id", None)
        if self._stop_signal.search(user_text) and active and self._code_signal.search(user_text):
            # Cancellation itself is persisted immediately; Docker process
            # termination is scheduled by the API or worker's next check.
            self.service.store.request_coding_cancel(str(active["id"]))
            # A running sandbox must be killed promptly, not only observed at
            # the next model-loop boundary. The persisted cancellation remains
            # authoritative if the current conversation is interrupted.
            asyncio.get_running_loop().create_task(self.service.runner.cancel(str(active["id"])))
            return f"Coding Agent task {active['id']} cancellation was requested. Confirm this plainly to the user."
        if self._status_signal.search(user_text) and (active or self._code_signal.search(user_text)):
            if active:
                return f"Coding Agent task {active['id']} is currently {active['status']}. Report only that durable status; do not invent progress."
            return "Coding Agent has no active task. Report that fact concisely."
        if active and self._instruction_signal.search(user_text) and self._code_signal.search(user_text):
            self.service.add_instruction(str(active["id"]), user_text)
            return f"Additional instruction was delivered to Coding Agent task {active['id']}. Acknowledge it; the task remains isolated and review-first."
        if self.service.runtime_settings.coding_auto_delegate and self._is_coding_request(user_text):
            task = self.service.create_task(
                user_text, session_id=session_id, source_message_id=source_message_id,
            )
            return (
                f"You delegated this coding request to Coding Agent task {task['id']} using {task['model']}. "
                "Tell the user it was queued, will run in an isolated copy, and no source changes apply without explicit review."
            )
        return None

    def _is_coding_request(self, user_text: str) -> bool:
        return bool(self._code_signal.search(user_text) and self._action_signal.search(user_text))
