from __future__ import annotations

from pathlib import Path

from apps.backend.app.context.manager import ContextManager
from apps.backend.app.storage.timeline import TimelineStore


def test_cross_episode_continuity_after_break(tmp_path: Path):
    db_path = tmp_path / "test_cross_episode.db"
    store = TimelineStore(db_path)
    store.init_db()

    session_night = "session_night_1am"
    session_morning = "session_morning_12pm"

    # 1. User and Iris talk at night
    u1, _ = store.append_message(
        session_id=session_night,
        role="user",
        content="Я пишу проект на Python и React, завтра планирую сделать авторизацию через JWT",
        input_mode="text",
    )

    store.append_message(
        session_id=session_night,
        role="assistant",
        content="Отличный план, завтра с утра займёмся авторизацией через JWT!",
        input_mode="text",
        turn_id=u1.turn_id,
        reply_to_message_id=u1.id,
    )

    # 2. Night episode closes due to overnight inactivity
    closed = store.close_current_episode(reason="inactivity_timeout")
    assert closed is not None
    assert closed["status"] == "closed"

    # Verify summary was generated immediately upon closing
    summary = store.get_episode_summary_for_episode(closed["id"])
    assert summary is not None, "Summary must be generated immediately upon episode close"
    assert "JWT" in summary["summary_text"] or "авторизаци" in summary["summary_text"]

    # 3. Next morning: user logs in with a NEW session_id and greets Iris
    u2, _ = store.append_message(
        session_id=session_morning,
        role="user",
        content="Привет, с чего начнём?",
        input_mode="text",
    )

    # Fetch context material for the morning session
    material = store.context_material("Привет, с чего начнём?", recent_turns=8, session_id=session_morning)

    # Verify recent messages from night are visible across session_id
    recent_contents = [r["content"] for r in material["recent"]]
    assert any("JWT" in c for c in recent_contents), f"Night messages should be present in recent turns: {recent_contents}"

    # Verify previous episode summary is present and tagged
    assert len(material["summaries"]) > 0
    prev_summary = material["summaries"][0]
    assert prev_summary.get("is_previous_episode") is True
    assert "JWT" in prev_summary["summary_text"] or "авторизаци" in prev_summary["summary_text"]

    # 4. ContextManager builds the prompt
    cm = ContextManager(store, max_tokens=3000, recent_turns=8)
    built = cm.build("Привет, с чего начнём?", session_id=session_morning, current_message_id=u2.id)

    # Verify built messages contain the previous conversation context header
    system_contents = [m.content for m in built.messages if m.role == "system"]
    assert any("Контекст недавнего прошлого разговора (что обсуждали до перерыва):" in c for c in system_contents)

    # Verify token budget is strictly respected
    assert built.token_estimate <= 3000


def test_cross_episode_on_the_fly_summarization_if_unsummarized(tmp_path: Path):
    db_path = tmp_path / "test_unsummarized.db"
    store = TimelineStore(db_path)
    store.init_db()

    # User and Iris talk
    u1, _ = store.append_message(
        session_id="s1",
        role="user",
        content="Мы настраиваем базу данных PostgreSQL для микросервисов",
        input_mode="text",
    )
    store.append_message(
        session_id="s1",
        role="assistant",
        content="Хорошо, настроим индексы и репликацию",
        input_mode="text",
        turn_id=u1.turn_id,
        reply_to_message_id=u1.id,
    )

    closed = store.close_current_episode(reason="inactivity_timeout")
    assert closed is not None

    # Simulate missing summary (e.g. crash or legacy database)
    with store._connect() as conn:
        conn.execute("DELETE FROM episode_summaries WHERE episode_id = ?", (closed["id"],))

    # Next session asks something with no keywords
    material = store.context_material("Доброе утро!", recent_turns=8, session_id="s2")

    # context_material must have generated it on the fly!
    assert len(material["summaries"]) > 0
    prev_summary = material["summaries"][0]
    assert prev_summary.get("is_previous_episode") is True
    assert "PostgreSQL" in prev_summary["summary_text"] or "микросервис" in prev_summary["summary_text"]
