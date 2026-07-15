import asyncio
from pathlib import Path

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import LLMProvider, LLMResponse
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineHistoryAdapter, TimelineStore


class CandidateProvider(LLMProvider):
    async def generate(self, messages):
        return LLMResponse(
            content=(
                '{"protocol_version":3,"reply":"Запомнила.","intent":"casual_chat",'
                '"affect":{"emotion":"neutral","intensity":1,"valence":0,"arousal":0},'
                '"gesture":{"name":"auto","intensity":1,"interrupt":true},'
                '"delivery":{"pace":"normal","emphasis":0},'
                '"memory_candidates":[{"kind":"preference","subject":"user","predicate":"likes",'
                '"value_text":"пьёт кофе без сахара","importance":0.7,"confidence":0.9,"sensitivity":"normal"}]}'
            ),
            model="test",
        )


class NoCandidateProvider(LLMProvider):
    async def generate(self, messages):
        return LLMResponse(
            content='{"protocol_version":3,"reply":"Хорошо.","intent":"casual_chat","memory_candidates":[]}',
            model="test",
        )


def test_agent_applies_llm_memory_candidates_after_reply(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "memory.sqlite3")
    store.init_db()
    service = MemoryService(
        store, RuntimeSettings(memory_mode="automatic"), llm_extraction_enabled=True,
    )
    agent = CharacterAgent(CandidateProvider(), TimelineHistoryAdapter(store), history_limit=5, memory_service=service)

    result = asyncio.run(agent.handle_user_message("session", "Я люблю кофе без сахара"))

    assert result["reply"] == "Запомнила."
    memories = store.list_memories(status="active")
    assert len(memories) == 1
    assert memories[0]["predicate"] == "likes"
    assert memories[0]["source_message_ids"]


def test_low_confidence_llm_candidate_is_ignored(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "memory.sqlite3")
    store.init_db()
    service = MemoryService(store, RuntimeSettings(memory_mode="automatic"), llm_extraction_enabled=True)
    message = TimelineHistoryAdapter(store).save_message("session", "user", "Наверное люблю чай")

    created = service.apply_llm_candidates([
        {"kind": "preference", "subject": "user", "predicate": "likes", "value_text": "чай", "confidence": 0.2},
    ], message)

    assert created == []
    assert store.list_memories() == []


def test_explicit_memory_uses_fallback_when_model_omits_candidates(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "memory.sqlite3")
    store.init_db()
    service = MemoryService(store, RuntimeSettings(memory_mode="automatic"), llm_extraction_enabled=True)
    agent = CharacterAgent(NoCandidateProvider(), TimelineHistoryAdapter(store), history_limit=5, memory_service=service)

    asyncio.run(agent.handle_user_message("session", "Запомни: моих разработчиков зовут Фетя и Ален"))

    assert store.list_memories(status="active")[0]["value_text"] == "моих разработчиков зовут Фетя и Ален"
