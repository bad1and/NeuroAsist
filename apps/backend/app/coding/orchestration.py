from __future__ import annotations

import asyncio
import re
import time

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
        r"(?:сделай|дай|передай|поручи|попроси|реализуй|исправь|измени|добавь|создай|напиши|проверь|запусти|"
        r"give|delegate|fix|implement|change|add|create|write|test|run)", re.IGNORECASE,
    )
    _stop_signal = re.compile(r"(?:останови|стоп|отмени|прекрати|cancel|stop)", re.IGNORECASE)
    _status_signal = re.compile(
        r"(?:статус|что\s+дела|что\s+(?:сделал|выполнил)|прогресс|результат|итог|готово|"
        r"status|progress|what\s+(?:did|was\s+done)|result|outcome|done)",
        re.IGNORECASE,
    )
    _instruction_signal = re.compile(r"(?:дополн|уточн|также|instead|ещ[её])", re.IGNORECASE)
    _agent_task_signal = re.compile(
        r"(?:coding\s*agent|(?:кодинг|кодовый)\s+агент|"
        r"(?:задач|код|файл|тест|переда|запуст|созда|напиш|смож|мож|сдела|выполн|результат|итог|готов).{0,64}\bагент[а-яё]*\b|"
        r"\bагент[а-яё]*\b.{0,64}(?:задач|код|файл|тест|переда|запуст|созда|напиш|сдела|выполн|результат|итог|готов)|"
        r"(?:task|code|file|test|delegat|run|creat|writ|did|complet|result|done).{0,64}\bagent\b|"
        r"\bagent\b.{0,64}(?:task|code|file|test|delegat|run|creat|writ|did|complet|result|done))",
        re.IGNORECASE,
    )
    _delegation_request_signal = re.compile(
        r"(?:хочу|хотел(?:s+бы)?|нужно|надо|давай|мож(?:ешь|но)|смож(?:ешь|ет)|пожалуйста|"
        r"i\s+want|i(?:'d|\s+would)\s+like|can\s+you|could\s+you|please|need).{0,96}"
        r"(?:coding\s*agent|(?:кодинг|кодовый)\s+агент|агент[а-яё]*|agent).{0,96}"
        r"(?:код|накод|файл|тест|программ|python|typescript|javascript|react|backend|frontend|api|bug|баг|ошибк)",
        re.IGNORECASE,
    )
    _forced_reply_prefix = "CODING_AGENT_FORCED_REPLY:"
    _deferred_confirmation_signal = re.compile(
        r"(?:^|\b)(?:(?:ирис\s+)?(?:ну\s+)?а\s+сейчас|(?:а\s+)?теперь|"
        r"давай|передай(?:\s+(?:е[ё]ё|задачу))?|запусти(?:\s+(?:е[ё]ё|задачу))?|"
        r"now|go\s+ahead|do\s+it|yes)(?:$|\b)",
        re.IGNORECASE,
    )
    _deferred_ttl_seconds = 10 * 60

    def __init__(self, service: CodingAgentService) -> None:
        self.service = service
        self._deferred_objectives: dict[str, tuple[str, float]] = {}

    def observe_user_message(self, session_id: str, user_text: str, source_message=None) -> str | None:
        if not self.service.enabled:
            tasks = self.service.store.list_coding_tasks(limit=30) if self.service.store is not None else []
            if self._status_signal.search(user_text) and self._is_coding_task_reference(user_text, has_tasks=bool(tasks)):
                latest = tasks[0] if tasks else None
                return self._forced_reply(self._disabled_status_reply(str(latest["status"]) if latest else None, user_text))
            if self._is_coding_delegation_request(user_text) or self._agent_task_signal.search(user_text):
                self._deferred_objectives[session_id] = (user_text, time.monotonic())
                return self._forced_reply(self._disabled_reply(user_text))
            if self._has_recent_deferred_objective(session_id) and (
                self._code_signal.search(user_text) or self._deferred_confirmation_signal.search(user_text)
            ):
                # A task is often described over two chat messages.  While
                # unavailable, keep the latest code-specific detail rather
                # than letting the conversational model fabricate an answer.
                if self._code_signal.search(user_text):
                    self._deferred_objectives[session_id] = (user_text, time.monotonic())
                return self._forced_reply(self._disabled_reply(user_text))
            return None
        tasks = self.service.store.list_coding_tasks(limit=30) if self.service.store is not None else []
        active = next((item for item in tasks if item["status"] in {"pending", "running", "waiting_for_input"}), None)
        source_message_id = getattr(source_message, "id", None)
        deferred = self._take_deferred_objective(session_id, user_text)
        if deferred is not None:
            task = self.service.create_task(deferred, session_id=session_id, source_message_id=source_message_id)
            return self._forced_reply(self._queued_reply(task, user_text))
        coding_reference = self._is_coding_task_reference(user_text, has_tasks=bool(tasks))
        if self._stop_signal.search(user_text) and active and coding_reference:
            # Cancellation itself is persisted immediately; Docker process
            # termination is scheduled by the API or worker's next check.
            self.service.store.request_coding_cancel(str(active["id"]))
            # A running sandbox must be killed promptly, not only observed at
            # the next model-loop boundary. The persisted cancellation remains
            # authoritative if the current conversation is interrupted.
            asyncio.get_running_loop().create_task(self.service.runner.cancel(str(active["id"])))
            return self._forced_reply(self._cancel_reply(user_text))
        if self._status_signal.search(user_text) and coding_reference:
            if active:
                return self._forced_reply(self._active_status_reply(str(active["status"]), user_text))
            latest = tasks[0] if tasks else None
            return self._forced_reply(self._idle_status_reply(str(latest["status"]) if latest else None, user_text))
        if active and self._instruction_signal.search(user_text) and coding_reference:
            self.service.add_instruction(str(active["id"]), user_text)
            return self._forced_reply(self._instruction_reply(user_text))
        if self.service.runtime_settings.coding_auto_delegate and self._is_coding_delegation_request(user_text):
            task = self.service.create_task(
                user_text, session_id=session_id, source_message_id=source_message_id,
            )
            # The person may have repeated a request that was made while the
            # agent was off.  It has now become a real task, so a later
            # "а сейчас" must not queue that old request a second time.
            self._deferred_objectives.pop(session_id, None)
            return self._forced_reply(self._queued_reply(task, user_text))
        if self._is_coding_delegation_request(user_text):
            return self._forced_reply(self._auto_delegate_disabled_reply(user_text))
        return None

    def _is_coding_request(self, user_text: str) -> bool:
        return bool(self._code_signal.search(user_text) and self._action_signal.search(user_text))

    def _is_coding_delegation_request(self, user_text: str) -> bool:
        """Recognise both imperative and natural-language delegation requests."""
        return bool(
            self._is_coding_request(user_text)
            or self._delegation_request_signal.search(user_text)
        )

    def _is_coding_task_reference(self, user_text: str, *, has_tasks: bool) -> bool:
        """Recognise task control/status language without treating a generic agent as coding.

        A completed task can be discussed with short phrasing such as
        ``что выполнил агент?``.  Once tasks exist, this is still an explicit
        enough reference to the Coding Agent, while an unrelated conversation
        mentioning an "agent" does not get intercepted.
        """
        return bool(
            self._code_signal.search(user_text)
            or (has_tasks and self._agent_task_signal.search(user_text))
        )

    @classmethod
    def forced_reply(cls, coordination: str | None) -> str | None:
        if coordination and coordination.startswith(cls._forced_reply_prefix):
            return coordination.removeprefix(cls._forced_reply_prefix)
        return None

    @classmethod
    def _forced_reply(cls, reply: str) -> str:
        """Mark a durable Coding Agent outcome for a model-free chat reply."""
        return cls._forced_reply_prefix + reply

    def _take_deferred_objective(self, session_id: str, user_text: str) -> str | None:
        deferred = self._deferred_objectives.get(session_id)
        if deferred is None:
            return None
        objective, created_at = deferred
        if time.monotonic() - created_at > self._deferred_ttl_seconds:
            self._deferred_objectives.pop(session_id, None)
            return None
        if not self._deferred_confirmation_signal.search(user_text):
            return None
        self._deferred_objectives.pop(session_id, None)
        return objective

    def _has_recent_deferred_objective(self, session_id: str) -> bool:
        deferred = self._deferred_objectives.get(session_id)
        if deferred is None:
            return False
        if time.monotonic() - deferred[1] <= self._deferred_ttl_seconds:
            return True
        self._deferred_objectives.pop(session_id, None)
        return False

    @staticmethod
    def _disabled_reply(user_text: str) -> str:
        if re.search(r"[А-Яа-яЁё]", user_text):
            return (
                "Coding Agent сейчас выключен, поэтому я не могу передать ему задачу "
                "или выполнить её. Включи его в разделе Coding Agent и отправь запрос ещё раз. "
                "Я не буду утверждать, что файл создан или тесты запущены, пока задача реально не выполнена."
            )
        return (
            "Coding Agent is currently turned off, so I cannot delegate or execute this task. "
            "Enable it in the Coding Agent section and send the request again. "
            "I will not claim that a file was created or tests were run until a real task completes."
        )

    @staticmethod
    def _uses_russian(user_text: str) -> bool:
        return bool(re.search(r"[А-Яа-яЁё]", user_text))

    def _queued_reply(self, task: dict[str, object], user_text: str) -> str:
        if self._uses_russian(user_text):
            return (
                "Задача передана Coding Agent и поставлена в очередь. "
                "Ход работы и результат видны в разделе Coding Agent."
            )
        return (
            "The task was delegated to Coding Agent and queued. "
            "Progress and the result are available in the Coding Agent section."
        )

    def _cancel_reply(self, user_text: str) -> str:
        return (
            "Запрос на остановку задачи Coding Agent отправлен." if self._uses_russian(user_text)
            else "A request to stop the Coding Agent task was sent."
        )

    def _active_status_reply(self, status: str, user_text: str) -> str:
        if self._uses_russian(user_text):
            return f"Coding Agent сейчас выполняет задачу (статус: {status}). Подробности и результат доступны в разделе Coding Agent."
        return f"Coding Agent is working on a task (status: {status}). Details and the result are available in the Coding Agent section."

    def _idle_status_reply(self, status: str | None, user_text: str) -> str:
        if self._uses_russian(user_text):
            if status:
                return f"Активной задачи Coding Agent нет. Статус последней задачи: {status}; детали доступны в разделе Coding Agent."
            return "Активных задач Coding Agent нет."
        if status:
            return f"Coding Agent has no active task. The latest task status is {status}; details are available in the Coding Agent section."
        return "Coding Agent has no active tasks."

    def _disabled_status_reply(self, status: str | None, user_text: str) -> str:
        if self._uses_russian(user_text):
            if status:
                return f"Coding Agent выключен. Последний сохранённый статус задачи: {status}; детали доступны в разделе Coding Agent."
            return "Coding Agent выключен, сохранённых задач нет."
        if status:
            return f"Coding Agent is turned off. The latest saved task status is {status}; details are available in the Coding Agent section."
        return "Coding Agent is turned off and there are no saved tasks."

    def _instruction_reply(self, user_text: str) -> str:
        return (
            "Дополнительная инструкция передана активной задаче Coding Agent." if self._uses_russian(user_text)
            else "The additional instruction was delivered to the active Coding Agent task."
        )

    def _auto_delegate_disabled_reply(self, user_text: str) -> str:
        return (
            "Coding Agent включён, но автоделегирование выключено. Включи его в разделе Coding Agent или создай задачу там вручную." if self._uses_russian(user_text)
            else "Coding Agent is enabled, but automatic delegation is off. Enable it in the Coding Agent section or create the task there manually."
        )
