import asyncio

from apps.backend.app.llm.base import LLMProvider, LLMResponse
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.memory.extraction_worker import MemoryExtractionWorker
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineStore
from apps.backend.app.storage.timeline import TimelineHistoryAdapter


class ExtractorProvider(LLMProvider):
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0
        self.messages = []

    async def generate(self, messages):
        self.calls += 1
        self.messages = messages
        return LLMResponse(content=self.payload, model="memory-test")


class TurnProvider(LLMProvider):
    async def generate(self, _messages):
        return LLMResponse(
            content='{"protocol_version":3,"reply":"Поняла.","intent":"casual_chat","memory_candidates":[]}',
            model="turn-test",
        )

    async def stream(self, _messages):
        yield "Поняла."


class CandidateTurnProvider(TurnProvider):
    async def generate(self, _messages):
        return LLMResponse(
            content=(
                '{"protocol_version":3,"reply":"Поняла.","intent":"casual_chat",'
                '"memory_candidates":[{"kind":"preference","subject":"user",'
                '"predicate":"likes","value_text":"кофе без сахара",'
                '"importance":0.7,"confidence":0.95,"sensitivity":"normal"}]}'
            ),
            model="turn-test",
        )


def _memory_service(tmp_path):
    store = TimelineStore(tmp_path / "memory.sqlite3")
    store.init_db()
    service = MemoryService(
        store,
        RuntimeSettings(memory_mode="balanced"),
        llm_extraction_enabled=True,
        async_extraction_enabled=True,
        auto_min_confidence=0.85,
        auto_min_importance=0.60,
    )
    return store, service


def test_background_extractor_saves_durable_preference_without_explicit_command(tmp_path) -> None:
    store, service = _memory_service(tmp_path)
    message, _ = store.append_message(role="user", content="Мне удобнее, когда ответы короткие и по делу", input_mode="voice")
    assert service.schedule_extraction(message) is True
    provider = ExtractorProvider(
        '{"memories":[{"kind":"preference","subject":"user","predicate":"prefers_response_length","value_text":"короткие ответы по делу","importance":0.7,"confidence":0.95,"sensitivity":"normal"}]}'
    )

    assert asyncio.run(MemoryExtractionWorker(store, service, provider).run_once()) is True

    memories = store.list_memories(status="active")
    assert provider.calls == 1
    assert len(memories) == 1
    assert memories[0]["predicate"] == "prefers_response_length"
    assert memories[0]["value_text"] == "короткие ответы по делу"


def test_background_extractor_keeps_sensitive_fact_in_review(tmp_path) -> None:
    store, service = _memory_service(tmp_path)
    message, _ = store.append_message(role="user", content="У меня аллергия на орехи", input_mode="text")
    service.schedule_extraction(message)
    provider = ExtractorProvider(
        '{"memories":[{"kind":"constraint","subject":"user","predicate":"allergy","value_text":"аллергия на орехи","importance":0.9,"confidence":0.99,"sensitivity":"sensitive"}]}'
    )

    asyncio.run(MemoryExtractionWorker(store, service, provider).run_once())

    assert store.list_memories(status="active") == []
    assert len(store.list_memories(status="candidate")) == 1


def test_background_extractor_redacts_secret_but_keeps_other_facts(tmp_path) -> None:
    store, service = _memory_service(tmp_path)
    message, _ = store.append_message(
        role="user",
        content=(
            "Я люблю длинные подробные ответы и моя текущая цель в разработке это "
            "закончить голосовой интерфейс до конца месяца, а мой пароль от почты 123456789"
        ),
        input_mode="text",
    )
    service.schedule_extraction(message)
    provider = ExtractorProvider('{"memories":[]}')

    asyncio.run(MemoryExtractionWorker(store, service, provider).run_once())

    submitted_prompt = provider.messages[-1].content
    assert "123456789" not in submitted_prompt
    assert "пароль" not in submitted_prompt.lower()
    assert "[секрет удалён]" in submitted_prompt
    active = {(item["predicate"], item["value_text"]) for item in store.list_memories(status="active")}
    assert ("prefers_response_length", "длинные подробные ответы") in active
    assert ("current_goal", "закончить голосовой интерфейс до конца месяца") in active


def test_background_extractor_never_runs_for_incognito_turn(tmp_path) -> None:
    store = TimelineStore(tmp_path / "memory.sqlite3")
    store.init_db()
    service = MemoryService(store, RuntimeSettings(memory_mode="automatic", memory_incognito=True))
    message, _ = store.append_message(role="user", content="Я люблю кофе", input_mode="text")

    assert service.schedule_extraction(message) is False
    assert store.claim_memory_extraction_job() is None


def test_text_and_live_turns_queue_extraction_only_after_the_reply(tmp_path) -> None:
    store, service = _memory_service(tmp_path)
    agent = CharacterAgent(TurnProvider(), TimelineHistoryAdapter(store), history_limit=5, memory_service=service)

    asyncio.run(agent.handle_user_message("session", "Я хочу закончить проект памяти", input_mode="text"))
    first_job = store.claim_memory_extraction_job()
    assert first_job is not None
    store.complete_summary_job(str(first_job["id"]))

    async def consume_live_turn() -> None:
        async for _chunk in agent.stream_user_message("session", "Мне нравятся короткие ответы", input_mode="voice"):
            pass

    asyncio.run(consume_live_turn())
    second_job = store.claim_memory_extraction_job()
    assert second_job is not None


def test_background_path_does_not_also_write_protocol_memory_candidates(tmp_path) -> None:
    store, service = _memory_service(tmp_path)
    agent = CharacterAgent(CandidateTurnProvider(), TimelineHistoryAdapter(store), history_limit=5, memory_service=service)

    asyncio.run(agent.handle_user_message("session", "Я люблю кофе без сахара", input_mode="text"))

    # The visible answer must not write the protocol's optional metadata.  One
    # background extractor is the only automatic write path.
    assert agent.last_memory_updates == []
    assert store.list_memories(status="active") == []
    extractor = ExtractorProvider(
        '{"memories":[{"kind":"preference","subject":"user","predicate":"likes",'
        '"value_text":"кофе без сахара","importance":0.7,"confidence":0.95,"sensitivity":"normal"}]}'
    )

    asyncio.run(MemoryExtractionWorker(store, service, extractor).run_once())

    memories = store.list_memories(status="active")
    assert len(memories) == 1
    assert memories[0]["value_text"] == "кофе без сахара"


def test_fallback_reply_still_queues_goal_extraction(tmp_path) -> None:
    class InvalidProvider(LLMProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, _messages):
            self.calls += 1
            return LLMResponse(content='{"reply":""}', model="turn-test")

    store, service = _memory_service(tmp_path)
    provider = InvalidProvider()
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), history_limit=5, memory_service=service)

    result = asyncio.run(agent.handle_user_message("session", "Моя текущая цель — закончить голосовой интерфейс до конца месяца"))

    assert provider.calls == 2
    assert result["reply"] == "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз."
    messages, _ = store.list_messages(10)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert store.claim_memory_extraction_job() is not None
