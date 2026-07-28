import asyncio
from pathlib import Path

from apps.backend.app.conversation.turn_coordinator import ConversationTurnCoordinator
from apps.backend.app.storage.timeline import TimelineStore


def test_duplicate_client_id_is_one_durable_turn(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = TimelineStore(tmp_path / "timeline.sqlite3")
        store.init_db()
        coordinator = ConversationTurnCoordinator(store)
        first = await coordinator.accept_user_turn(
            session_id="chat", content="длинная идея", input_mode="text", client_message_id="client-1",
        )
        repeated = await coordinator.accept_user_turn(
            session_id="chat", content="длинная идея", input_mode="text", client_message_id="client-1",
        )
        assert first.created is True
        assert repeated.created is False
        assert repeated.user_message_id == first.user_message_id
        assert repeated.generation == first.generation == 1
        assert len(store.list_messages(20)[0]) == 1

    asyncio.run(scenario())


def test_new_turn_commits_before_it_interrupts_previous_generation(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = TimelineStore(tmp_path / "timeline.sqlite3")
        store.init_db()
        coordinator = ConversationTurnCoordinator(store)
        first = await coordinator.accept_user_turn(session_id="chat", content="важная идея", input_mode="text")
        lease = await coordinator.begin_assistant(first)
        running = asyncio.create_task(asyncio.sleep(30))
        coordinator.register_generation_task(lease, running)

        second = await coordinator.accept_user_turn(session_id="chat", content="Ирис", input_mode="text")
        await asyncio.sleep(0)
        messages, _ = store.list_messages(20)
        assert [message.content for message in messages if message.role == "user"] == ["важная идея", "Ирис"]
        assert store.get_message(lease.assistant_message_id).status == "interrupted"
        assert running.cancelled()
        assert second.generation == 2

    asyncio.run(scenario())


def test_context_is_bounded_by_current_message_sequence(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    earlier, _ = store.append_message(role="user", content="раньше", input_mode="text")
    current = store.accept_user_turn(session_key="chat", content="сейчас", input_mode="text")
    later, _ = store.append_message(role="user", content="позже", input_mode="text")

    material = store.context_material("сейчас", recent_turns=8, current_message_id=current.message.id)
    assert material["causal_upper_bound"] == current.message.sequence_no
    assert [row["id"] for row in material["recent"]] == [earlier.id]
    assert later.sequence_no > current.message.sequence_no
