"""Durable, explicitly requested reminders linked to the existing commitments.

Delivery is an outbox: a due revision stays pending until the UI acknowledges it.
Restarting the core or sleeping Windows never removes a due reminder. Consumers
deduplicate its stable delivery_token before showing a native notification.
"""
from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Callable
from threading import Lock
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.backend.app.skills.runtime import Skill


def utc_date(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Укажите время с часовым поясом.")
    return result.astimezone(UTC)


def explicit_reminder(text: str) -> bool:
    return bool(re.search(r"(?:^|[.!?;,]\s*)(?:(?:ирис|iris|слушай|пожалуйста|ну|эй|так|ага|да|и|ещё|еще)[,\s:—-]+)*(?:напомни(?:те)?|можешь\s+(?:мне\s+)?напомнить|поставь\s+(?:мне\s+)?напоминание|создай\s+(?:мне\s+)?напоминание|remind\s+me)\b", text, re.I)) and not bool(re.search(r"\b(?:не\s+напоминай|не\s+надо\s+напоминать|как\s+(?:поставить|создать)\s+напоминание)\b", text, re.I))


def failed_reminder_reply(metadata: dict | None, requested_text: str = "", model_reply: str = "") -> str | None:
    if not metadata or metadata.get("name") != "create_reminder":
        if explicit_reminder(requested_text):
            question = re.search(r"во\s+сколько|когда|какую\s+дату|какой\s+день|утром\s+или\s+вечером|что\s+напомнить", model_reply, re.I)
            claimed = re.search(r"напомню|(?:создан|сохран[её]н|поставлен|установлен)[оа]?|(?:создал|сохранил|поставил)[аи]?|готово", model_reply, re.I)
            if question and not claimed:
                return None
            return "Напоминание пока не создано. Уточни дату и время, и попробуем ещё раз."
        return None
    result = metadata.get("reminder_result") or {}
    if metadata.get("status") == "ok" and result.get("status") == "scheduled":
        # The acknowledgement is a receipt for the saved deadline, not a new
        # model prediction. Use the same receipt for text and live voice.
        due = datetime.fromisoformat(result.get("display_due_at") or result["due_at"])
        return f"Напоминание сохранено: {result['title']} — {due:%d.%m.%Y} в {due:%H:%M} ({due.tzname()})."
    if result.get("status") == "needs_time":
        return "Во сколько и в какой день тебе напомнить? Пока напоминание не создано."
    if result.get("status") in {"cancelled", "completed"}:
        state = "отменено" if result["status"] == "cancelled" else "выполнено"
        return f"Это напоминание уже {state}. Повторный запрос не создаёт его заново."
    if result.get("status") == "time_passed":
        return "Это время уже прошло. На какую дату поставить напоминание?"
    return "Напоминание не сохранилось. Попробуй ещё раз и укажи точное время."


def reminder_request_from_context(text: str, context) -> str:
    if explicit_reminder(text) or (not explicit_reminder_time(text) and not re.search(r"\b(?:завтра|сегодня|послезавтра|через|утром|вечером|понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье|tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}[:.]\d{2}|в\s+\d{1,2})\b", text, re.I)):
        return text
    turns = [message for message in context if getattr(message, "role", "") in {"user", "assistant"}]
    if turns and turns[-1].role == "user" and turns[-1].content.strip() == text.strip():
        turns = turns[:-1]
    if len(turns) >= 2 and turns[-1].role == "assistant" and re.search(r"когда|како[ей]\s+(?:время|день)|во\s+сколько|уточни|\bwhen\b|what time|which day|clarify", turns[-1].content, re.I) and turns[-2].role == "user" and explicit_reminder(turns[-2].content):
        return turns[-2].content + "\nУточнение времени пользователем: " + text
    return text


def explicit_reminder_time(text: str) -> bool:
    return resolve_reminder_time(text, datetime.now(UTC)) is not None


class ReminderArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=500)
    due_at: str = Field(min_length=10, max_length=50, description="Точная дата ISO 8601 с часовым поясом; если время неоднозначно, сначала уточни его у пользователя.")
    timezone_label: str = Field(default="", max_length=80)

    @field_validator("due_at")
    @classmethod
    def validate_due(cls, value: str) -> str:
        utc_date(value)
        return value


_NUMBERS = dict(zip(
    "один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать двадцать".split(), range(1, 21)))
_NUMBERS.update(dict(zip("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(), range(1, 21))))
_NUMBERS.update({"одну": 1, "одна": 1, "две": 2, "час": 1, "полтора": 1.5, "полторы": 1.5})
_WEEKDAYS = dict(zip("понедельник вторник среду четверг пятницу субботу воскресенье".split(), range(7)))
_WEEKDAYS.update(dict(zip("monday tuesday wednesday thursday friday saturday sunday".split(), range(7))))
_MONTHS = dict(zip("января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split(), range(1, 13)))
_MONTHS.update(dict(zip("january february march april may june july august september october november december".split(), range(1, 13))))


def resolve_reminder_time(text: str, now: datetime) -> datetime | None:
    """Ground supported dates in the request; ask instead of guessing unknown dates."""
    text = text.casefold()
    if re.search(r"\b(?:кажд\w*|ежеднев\w*|еженедел\w*|every|daily|weekly)\b", text):
        return None
    local_now = now.astimezone()
    if re.search(r"\bмск\b|москв|\bmoscow\b", text):
        local_now = now.astimezone(timezone(timedelta(hours=3)))
    elif zone := re.search(r"\b(?:utc|gmt)(?:\s*([+-])(\d{1,2})(?::([0-5]\d))?)?", text):
        offset = (int(zone[2] or 0) * 60 + int(zone[3] or 0)) * (-1 if zone[1] == "-" else 1)
        if abs(offset) > 14 * 60:
            return None
        local_now = now.astimezone(timezone(timedelta(minutes=offset)))

    text = re.sub(r"\b(?:в|at)\s+(двадцать\s+(?:один|два|три)|" + "|".join(_NUMBERS) + r")\b",
        lambda m: "в " + str(20 + _NUMBERS[m[1].split()[1]] if m[1].startswith("двадцать ") else _NUMBERS[m[1]]), text)
    text = re.sub(r"\b(?:в\s+)?полдень\b|\b(?:at\s+)?noon\b", "в 12:00", text)
    text = re.sub(r"\b(?:в\s+)?полночь\b|\b(?:at\s+)?midnight\b", "в 00:00", text)
    clocks = list(re.finditer(r"\b(?:в|at)\s+(\d{1,2})(?::([0-5]\d))?(?![\d./:-])\b|(?<![\d:+-])\b(\d{1,2}):([0-5]\d)\b|\b(\d{1,2})\s*(am|pm)\b", text))
    relative = re.search(r"\b(?:через|in)\s+(\d+(?:[.,]\d+)?|" + "|".join(_NUMBERS) + r")\s*(минут\w*|час\w*|дн\w*|день|недел\w*|minutes?|hours?|days?|weeks?)\b", text)
    if re.search(r"\bчерез\s+полчаса\b|\bin\s+half\s+an?\s+hour\b", text):
        return local_now + timedelta(minutes=30) if not clocks else None
    if re.search(r"\bчерез\s+(?:час|минуту)\b|\bin\s+an?\s+(?:hour|minute)\b", text):
        if clocks:
            return None
        return local_now + timedelta(minutes=1 if re.search(r"минуту|minute", text) else 60)
    days_offset = None
    if relative:
        quantity, unit = relative[1], relative[2]
        amount = _NUMBERS[quantity] if quantity in _NUMBERS else float(quantity.replace(",", "."))
        seconds = 60 if unit.startswith(("минут", "minute")) else 3600 if unit.startswith(("час", "hour")) else 604800 if unit.startswith(("недел", "week")) else 86400
        if amount <= 0 or amount * seconds > 5 * 366 * 86400:
            return None
        if not clocks:
            return local_now + timedelta(seconds=amount * seconds)
        if seconds < 86400 or amount * seconds % 86400:
            return None
        days_offset = int(amount * seconds / 86400)
    if not clocks:
        return None
    clock = clocks[-1]
    hour, minute = int(clock[1] or clock[3] or clock[5]), int(clock[2] or clock[4] or 0)
    if hour > 23:
        return None
    suffix = text[clock.end():].lstrip()
    qualifier_match = re.match(r"(утра|утром|вечера|вечером|дня|ночи|am|pm)\b", suffix)
    qualifier = clock[6] or (qualifier_match[1] if qualifier_match else "")
    if qualifier:
        if hour > 12:
            return None
        if qualifier in {"pm", "вечера", "вечером", "дня"}:
            hour = hour % 12 + 12
        else:
            # 'Tomorrow at twelve at night' can mean either edge of tomorrow.
            # Ask for an explicit date/00:00 rather than silently choosing noon.
            if hour == 12 and qualifier == "ночи":
                return None
            hour %= 12
    elif clock[1] and not clock[2] and 0 < hour < 12:
        return None

    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    without_clock = text[:clock.start()] + " " + text[clock.end():]
    if iso := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", without_clock):
        year, month, day = map(int, iso.groups())
    else:
        numeric = re.search(r"(?<![\d:])(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?(?![\d:])", without_clock)
        named = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(" + "|".join(_MONTHS) + r")(?:\s+(\d{4}))?\b", without_clock)
        month_first = re.search(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", without_clock)
        day_only = re.search(r"\b(\d{1,2})\s*(?:-?го|числа|st|nd|rd|th)\b", without_clock)
        if numeric or named or month_first:
            date = numeric or named or month_first
            day = int(date[2] if month_first and not numeric and not named else date[1])
            month = int(date[2]) if numeric else _MONTHS[date[2] if named else date[1]]
            year = int(date[3]) if date[3] else local_now.year
            if not 1 <= month <= 12 or not 1 <= day <= 31:
                return None
            if not date[3]:
                for year in range(local_now.year, local_now.year + 5):
                    try:
                        if target.replace(year=year, month=month, day=day) > now:
                            break
                    except ValueError:
                        continue
                else:
                    return None
        elif day_only:
            day = int(day_only[1])
            if not 1 <= day <= 31:
                return None
            for shift in range(13):
                month_index = local_now.month - 1 + shift
                year, month = local_now.year + month_index // 12, month_index % 12 + 1
                try:
                    candidate = target.replace(year=year, month=month, day=day)
                    if candidate.date() >= local_now.date():
                        break
                except ValueError:
                    continue
            else:
                return None
        else:
            days = list(re.finditer(r"\b(послезавтра|завтра|сегодня|day after tomorrow|tomorrow|today|" + "|".join(_WEEKDAYS) + r")\b", text))
            if days_offset is not None:
                return target + timedelta(days=days_offset)
            if days:
                when = days[-1][1]
                delta = ((_WEEKDAYS[when] - local_now.weekday()) % 7) if when in _WEEKDAYS else 2 if when in {"послезавтра", "day after tomorrow"} else 1 if when in {"завтра", "tomorrow"} else 0
                if when in _WEEKDAYS and delta == 0 and (target <= now or re.search(r"следующ|next", text)):
                    delta = 7
                return target + timedelta(days=delta)
            if re.search(r"через|следующ|месяц|год|числа|\b(?:in|next|month|year|week|" + "|".join(_MONTHS) + r")\b", without_clock):
                return None
            return target
    try:
        return target.replace(year=year, month=month, day=day)
    except ValueError:
        return None


class ReminderService:
    def __init__(self, store, publish=None, now: Callable[[], datetime] | None = None):
        self.store = store
        self.publish = publish
        self.now = now or (lambda: datetime.now(UTC))
        self._announced: dict[str, datetime] = {}
        self._schema_ready = False
        self._schema_lock = Lock()

    def _ensure_schema(self):
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self.store._connect() as connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS scheduled_reminders (
                commitment_id TEXT PRIMARY KEY REFERENCES memory_commitments(id) ON DELETE CASCADE,
                source_key TEXT NOT NULL UNIQUE, timezone_label TEXT NOT NULL,
                revision TEXT NOT NULL, delivered_at TEXT, created_at TEXT NOT NULL
            )""")
            self._schema_ready = True

    def create(self, title: str, due_at: str, *, timezone_label: str = "", source_key: str | None = None) -> dict:
        self._ensure_schema()
        if source_key:
            with self.store._connect() as connection:
                existing_request = connection.execute("SELECT commitment_id FROM scheduled_reminders WHERE source_key = ?", (source_key,)).fetchone()
            if existing_request is not None:
                return self.get(existing_request["commitment_id"])
        due, now = utc_date(due_at), self.now()
        if due <= now or due > now + timedelta(days=366 * 5):
            raise ValueError("Выберите будущую дату в пределах пяти лет.")
        title = title.strip()
        if not title or len(title) > 500:
            raise ValueError("Укажите короткий текст напоминания.")
        key = source_key or uuid4().hex
        identifier = uuid5(NAMESPACE_URL, "iris:reminder:" + key).hex
        with self.store.consolidation_transaction() as connection:
            existing = connection.execute("SELECT commitment_id FROM scheduled_reminders WHERE source_key = ?", (key,)).fetchone()
            if existing is None:
                self.store.create_commitment({"id": identifier, "kind": "open_loop", "title": title,
                    "due_at": due.isoformat(), "confidence": 1, "user_locked": True, "extractor_version": "reminder-v1"})
                connection.execute("INSERT INTO scheduled_reminders VALUES (?, ?, ?, ?, NULL, ?)",
                    (identifier, key, timezone_label or datetime.fromisoformat(due_at.replace("Z", "+00:00")).tzname(), uuid4().hex, now.isoformat()))
        item = self.get(identifier)
        if existing is None and self.publish is not None:
            self.publish("reminder.created", "info", "Напоминание сохранено", item)
        return item

    def list(self, *, due_only: bool = False) -> list[dict]:
        self._ensure_schema()
        with self.store._connect() as connection:
            rows = connection.execute("""SELECT c.*, r.timezone_label, r.revision AS delivery_token, r.delivered_at
                FROM memory_commitments c JOIN scheduled_reminders r ON c.id = r.commitment_id
                ORDER BY c.due_at, c.created_at""").fetchall()
        items = [dict(row) for row in rows]
        if due_only:
            items = [row for row in items if row["status"] == "open" and row["delivered_at"] is None and utc_date(row["due_at"]) <= self.now()]
        return items

    def get(self, identifier: str) -> dict:
        item = next((row for row in self.list() if row["id"] == identifier), None)
        if item is None:
            raise KeyError(identifier)
        return item

    def for_request(self, source_key: str) -> dict | None:
        self._ensure_schema()
        with self.store._connect() as connection:
            row = connection.execute("SELECT commitment_id FROM scheduled_reminders WHERE source_key = ?", (source_key,)).fetchone()
        return self.get(row["commitment_id"]) if row else None

    def update(self, identifier: str, *, status: str | None = None, due_at: str | None = None) -> dict:
        if status is not None and status not in {"open", "completed", "cancelled"}:
            raise ValueError("Неизвестное состояние напоминания.")
        due = utc_date(due_at) if due_at else None
        if due and (due <= self.now() or due > self.now() + timedelta(days=366 * 5)):
            raise ValueError("Выберите будущую дату в пределах пяти лет.")
        with self.store.consolidation_transaction() as connection:
            self.get(identifier)
            changes = {key: value for key, value in {"status": status, "due_at": due.isoformat() if due else None}.items() if value is not None}
            self.store.update_commitment(identifier, changes)
            if due or status is not None:
                connection.execute("UPDATE scheduled_reminders SET revision = ?, delivered_at = NULL WHERE commitment_id = ?", (uuid4().hex, identifier))
        return self.get(identifier)

    def acknowledge(self, identifier: str, token: str) -> bool:
        self._ensure_schema()
        with self.store._connect() as connection:
            cursor = connection.execute("UPDATE scheduled_reminders SET delivered_at = ? WHERE commitment_id = ? AND revision = ? AND delivered_at IS NULL", (self.now().isoformat(), identifier, token))
            return cursor.rowcount == 1

    def tick(self):
        if self.publish is None:
            return
        for item in self.list(due_only=True):
            token = item["delivery_token"]
            if token in self._announced and self.now() - self._announced[token] < timedelta(seconds=30):
                continue
            self.publish("reminder.due", "info", "Пришло время напоминания", item)
            self._announced[token] = self.now()
        cutoff = self.now() - timedelta(minutes=2)
        self._announced = {key: value for key, value in self._announced.items() if value > cutoff}

    async def run(self):
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                # An unavailable database must not terminate the delivery loop.
                import logging
                logging.getLogger(__name__).exception("Reminder delivery tick failed")
            await asyncio.sleep(5)


def reminder_skill(service: ReminderService, context: Callable[[], dict]) -> Skill:
    async def execute(args: ReminderArguments):
        current = context()
        if not explicit_reminder(current.get("text", "")) or not current.get("source_id"):
            return {"status": "not_requested", "message": "Напоминание не создано: нужна явная просьба пользователя."}
        source_key = "turn:" + str(current["source_id"])
        existing = await asyncio.to_thread(service.for_request, source_key)
        if existing is not None and existing["status"] != "open":
            return {"status": existing["status"], "id": existing["id"]}
        due = resolve_reminder_time(current["text"], service.now()) if existing is None else None
        if existing is None and due is None:
            return {"status": "needs_time", "message": "Уточни точную дату, время и при необходимости часовой пояс. Напоминание пока не создано."}
        due_at = due.isoformat() if due else existing["due_at"]
        if existing is None and utc_date(due_at) <= service.now():
            return {"status": "time_passed", "message": "Это время уже прошло. Уточни будущую дату, напоминание не создано."}
        item = existing or await asyncio.to_thread(service.create, args.title, due_at,
            timezone_label=datetime.fromisoformat(due_at).tzname(), source_key=source_key)
        display_zone = due.tzinfo if due else datetime.fromisoformat(item["due_at"]).tzinfo
        if zone := re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", item["timezone_label"]):
            minutes = (int(zone[2]) * 60 + int(zone[3])) * (-1 if zone[1] == "-" else 1)
            display_zone = timezone(timedelta(minutes=minutes))
        return {"status": "scheduled", "id": item["id"], "title": item["title"], "due_at": item["due_at"],
            "display_due_at": utc_date(item["due_at"]).astimezone(display_zone).isoformat(),
            "timezone_label": item["timezone_label"], "delivery": "Iris должна быть запущена; пропущенный срок будет показан при следующем запуске."}

    return Skill("create_reminder", "Создай локальное напоминание только по явной просьбе напомнить. Не создавай по плану, цитате или рассуждению. Уточни недостающие дату и время. Текущее местное время: " + datetime.now().astimezone().isoformat(),
        ReminderArguments, execute, lambda: explicit_reminder(context().get("text", "")))
