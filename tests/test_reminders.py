from datetime import UTC, datetime, timedelta
import asyncio

import pytest

from apps.backend.app.reminders import ReminderArguments, ReminderService, explicit_reminder, reminder_skill, resolve_reminder_time, failed_reminder_reply, reminder_request_from_context
from apps.backend.app.storage.timeline import TimelineStore


@pytest.fixture
def reminders(tmp_path):
    clock = [datetime(2026, 10, 19, 12, tzinfo=UTC)]
    store = TimelineStore(tmp_path / "reminders.sqlite3")
    store.init_db()
    return ReminderService(store, now=lambda: clock[0]), clock


def test_reminder_survives_restart_until_current_revision_is_acknowledged(reminders):
    service, clock = reminders
    item = service.create("Сборка", "2026-10-19T16:00:00+03:00", source_key="turn-1")
    assert service.create("Повтор сетевого запроса", "2026-10-19T16:00:00+03:00", source_key="turn-1")["id"] == item["id"]
    assert len(service.list()) == 1
    assert not service.list(due_only=True)
    clock[0] += timedelta(hours=2)
    restarted = ReminderService(service.store, now=lambda: clock[0])
    assert restarted.list(due_only=True)[0]["id"] == item["id"]
    assert not restarted.acknowledge(item["id"], "stale")
    assert restarted.acknowledge(item["id"], item["delivery_token"])
    assert not restarted.list(due_only=True)
    assert not restarted.acknowledge(item["id"], item["delivery_token"])


def test_cancelled_request_is_not_recreated_by_a_retried_tool_call(reminders):
    service, _ = reminders
    skill = reminder_skill(service, lambda: {"text": "Напомни через пять минут", "source_id": "cancelled-turn"})
    args = ReminderArguments(title="Сборка", due_at="2026-10-19T19:00:00+03:00")
    item = asyncio.run(skill.execute(args))
    service.update(item["id"], status="cancelled")
    replay = asyncio.run(skill.execute(args))
    assert replay["status"] == "cancelled"
    assert len(service.list()) == 1
    assert "отменено" in failed_reminder_reply({"name": "create_reminder", "status": "ok", "reminder_result": replay})


def test_snoozing_invalidates_old_ack_and_completion_prevents_delivery(reminders):
    service, clock = reminders
    old = service.create("Проверить", "2026-10-19T16:00:00+03:00")
    updated = service.update(old["id"], due_at="2026-10-19T18:00:00+03:00")
    assert updated["delivery_token"] != old["delivery_token"]
    assert not service.acknowledge(old["id"], old["delivery_token"])
    service.update(old["id"], status="completed")
    clock[0] += timedelta(days=1)
    assert not service.list(due_only=True)
    assert service.store.get_commitment(old["id"])["status"] == "completed"


def test_invalid_dates_and_non_requests_do_not_schedule(reminders):
    service, _ = reminders
    for due in ("2026-10-19T15:00:00", "2026-10-18T15:00:00+03:00", "invalid"):
        with pytest.raises(ValueError):
            service.create("Тест", due)
    assert not service.list()
    assert explicit_reminder("Напомни завтра в 19:00 проверить сборку")
    assert not explicit_reminder("Хочу как-нибудь проверить сборку")
    assert not explicit_reminder("Не напоминай про сборку")
    assert not explicit_reminder("Как создать напоминание?")
    assert not explicit_reminder("В документе написано «Напомни завтра в 19:00», объясни эту фразу")
    assert explicit_reminder("Ирис, пожалуйста, напомни завтра в 19:00")
    assert explicit_reminder("Можешь мне напомнить завтра в 19:00?")


def test_skill_needs_explicit_current_request_and_is_idempotent(reminders):
    service, _ = reminders
    context = {"text": "Думаю о сборке", "source_id": "turn-2"}
    skill = reminder_skill(service, lambda: context)
    args = ReminderArguments(title="Сборка", due_at="2026-10-19T19:00:00+03:00")
    assert not skill.available()
    assert asyncio.run(skill.execute(args))["status"] == "not_requested"
    context["text"] = "Напомни в 19:00 про сборку"
    assert skill.available()
    assert asyncio.run(skill.execute(args))["status"] == "scheduled"
    asyncio.run(skill.execute(args))
    assert len(service.list()) == 1


def test_due_delivery_retries_without_ack_and_does_not_publish_completed(reminders):
    service, clock = reminders
    events = []
    item = service.create("Проверить", "2026-10-19T16:00:00+03:00")
    service.publish = lambda *args: events.append(args)
    clock[0] += timedelta(hours=2)
    service.tick(); service.tick()
    assert len(events) == 1
    clock[0] += timedelta(seconds=31)
    service.tick()
    assert len(events) == 2
    service.update(item["id"], status="cancelled")
    clock[0] += timedelta(minutes=1)
    service.tick()
    assert len(events) == 2


@pytest.mark.parametrize("text,expected", [
    ("Напомни 23-го в 19:00 мск", "2026-10-23T19:00:00+03:00"),
    ("Remind me tomorrow at 19:00 UTC+03:00", "2026-10-21T19:00:00+03:00"),
    ("Remind me tomorrow at 7 pm UTC+03:00", "2026-10-21T19:00:00+03:00"),
    ("Напомни завтра в семь вечера мск", "2026-10-21T19:00:00+03:00"),
    ("Напомни завтра в 00:00 мск", "2026-10-21T00:00:00+03:00"),
    ("Напомни 22 октября в полночь мск", "2026-10-22T00:00:00+03:00"),
    ("Напомни завтра в два ночи мск", "2026-10-21T02:00:00+03:00"),
    ("Напомни через пять минут", "2026-10-20T08:05:00+00:00"),
    ("Remind me in five minutes", "2026-10-20T08:05:00+00:00"),
    ("Напомни через полчаса", "2026-10-20T08:30:00+00:00"),
    ("Напомни через два дня в 19:00 мск", "2026-10-22T19:00:00+03:00"),
    ("Напомни 23.11 в 19:00 мск", "2026-11-23T19:00:00+03:00"),
    ("Напомни 23-11-2026 в 19:00 мск", "2026-11-23T19:00:00+03:00"),
    ("Напомни 23октября в 19:00 мск", "2026-10-23T19:00:00+03:00"),
    ("Remind me November 23rd at 7 pm UTC+03:00", "2026-11-23T19:00:00+03:00"),
    ("Напомни 2026-11-23 в 19:00 мск", "2026-11-23T19:00:00+03:00"),
    ("Напомни завтра в 19:00 UTC-05:00", "2026-10-21T19:00:00-05:00"),
])
def test_deadline_is_grounded_in_request_instead_of_a_model_default(text, expected):
    now = datetime(2026, 10, 20, 8, tzinfo=UTC)
    assert resolve_reminder_time(text, now) == datetime.fromisoformat(expected)


@pytest.mark.parametrize("text", [
    "Напомни завтра в двенадцать ночи", "Напомни завтра в семь", "Remind me tomorrow at 7",
    "Напомни 30.02.2027 в 19:00", "Напомни в следующем месяце в 19:00",
    "Напомни через пять минут в 19:00", "Напомни завтра в 25:00", "Напомни завтра в 19:00 UTC+15:00",
    "Remind me next November at 19:00", "Напомни каждый день в 19:00",
])
def test_ambiguous_or_unsupported_date_is_never_changed_to_today(text):
    assert resolve_reminder_time(text, datetime(2026, 10, 20, 8, tzinfo=UTC)) is None


@pytest.mark.parametrize("now,text,expected", [
    ("2026-12-31T18:00:00+03:00", "Напомни завтра в 19:00 мск", "2027-01-01T19:00:00+03:00"),
    ("2026-10-31T18:00:00+03:00", "Напомни 3-го в 19:00 мск", "2026-11-03T19:00:00+03:00"),
    ("2027-02-28T18:00:00+03:00", "Напомни 29.02 в 19:00 мск", "2028-02-29T19:00:00+03:00"),
])
def test_calendar_rollover_and_leap_day(now, text, expected):
    assert resolve_reminder_time(text, datetime.fromisoformat(now)) == datetime.fromisoformat(expected)


def test_english_spoken_clarification_keeps_the_original_reminder_request():
    from apps.backend.app.llm.base import ChatMessage
    history = [ChatMessage(role="user", content="Remind me tomorrow about the build"),
        ChatMessage(role="assistant", content="What time should I remind you?")]
    request = reminder_request_from_context("At seven pm UTC+03:00", history)
    assert explicit_reminder(request)
    assert resolve_reminder_time(request, datetime(2026, 10, 20, 8, tzinfo=UTC)) == datetime.fromisoformat("2026-10-21T19:00:00+03:00")


def test_saved_deadline_is_replayed_after_it_has_passed_and_receipt_cannot_invent_time(reminders):
    service, clock = reminders
    skill = reminder_skill(service, lambda: {"text": "Напомни через пять минут", "source_id": "stable-turn"})
    args = ReminderArguments(title="Сборка", due_at="2026-12-25T19:00:00+03:00")
    first = asyncio.run(skill.execute(args))
    assert first["status"] == "scheduled"
    assert datetime.fromisoformat(first["due_at"]) == clock[0] + timedelta(minutes=5)
    clock[0] += timedelta(hours=1)
    replay = asyncio.run(skill.execute(args))
    assert replay["due_at"] == first["due_at"]
    assert replay["display_due_at"] == first["display_due_at"]
    receipt = failed_reminder_reply({"name": "create_reminder", "status": "ok", "reminder_result": first})
    assert "19.10.2026" in receipt and "25.12.2026" not in receipt
    old_token = service.get(first["id"])["delivery_token"]
    service.update(first["id"], status="cancelled")
    assert not service.acknowledge(first["id"], old_token)
    assert not service.list(due_only=True)
