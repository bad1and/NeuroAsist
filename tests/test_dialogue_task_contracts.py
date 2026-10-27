"""Sequential regressions from the 23 October dialogues, preserving Iris's register."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.dialogue_pacing import infer_dialogue_pacing
from apps.backend.app.agents.character.dialogue_style import dialogue_style_prompt
from apps.backend.app.agents.character.search_intent import explicit_query_revision
from apps.backend.app.context.manager import ContextManager
from apps.backend.app.context.task_frame import TASK_PREFIX, frame_from_context, resolve_task_frame
from apps.backend.app.conversation.adjudicator import StructuredConversationAdjudicator
from apps.backend.app.conversation.feedback import feedback_prompt, user_feedback
from apps.backend.app.conversation.schemas import ConversationAction, ConversationDecision, DecisionReason, EventAppraisal
from apps.backend.app.llm.base import ChatMessage, LLMResponse, current_llm_call_purpose
from apps.backend.app.memory.consolidation import ConsolidationResult
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import TimelineHistoryAdapter, TimelineStore
from tests.test_memory_retention import write
from tests.test_search_recovery import History, ReplayLLM


@pytest.fixture
def anyio_backend():
    return "asyncio"


GAME = ["Давай поиграем в игру", "Я говорю слово, а ты должна подобрать синоним", "Отвечай одним словом без ничего лишнего"]


def user_messages(texts):
    return [ChatMessage(role="user", content=text) for text in texts]


def test_frame_keeps_the_relation_and_format_instead_of_treating_name_as_a_call():
    context = user_messages(GAME)
    for word in ["небо", "огурец", "арбуз", "Ирис", "взрыв", "пока"]:
        pacing = infer_dialogue_pacing(word, context)
        assert pacing.mode == "constrained"
        cue = pacing.prompt_block(input_mode="voice", recent_messages=context, user_text=word)
        assert "синоним" in cue and "ровно одно слово" in cue
        assert "Коротко отзовись" not in cue
    assert infer_dialogue_pacing("Ирис").turn_kind == "address"


@pytest.mark.parametrize("text", [
    "С игрой закончили, найди песню", "Хватит играть", "Сменим тему", "Найди популярную песню про машину",
    "Помаши левой рукой", "Отвечай теперь обычно",
    "Можешь найти другую песню", "Запомни, меня зовут Роман",
])
def test_task_ends_on_explicit_finish_or_new_task(text):
    assert not resolve_task_frame(user_messages([*GAME, text])).active


@pytest.mark.parametrize("text", [
    'Он сказал: «Давай поиграем в синонимы»', '«Давай поиграем в синонимы»',
    "Я люблю подбирать синонимы", "Подбери синоним к слову взрыв",
])
def test_mentions_quotes_and_one_off_requests_do_not_start_a_persistent_game(text):
    assert not resolve_task_frame(user_messages([text])).active


def test_frame_survives_small_recent_window_and_does_not_cross_sessions(tmp_path):
    store = TimelineStore(tmp_path / "timeline.db")
    store.init_db()
    for text in [*GAME, *[f"слово{i}" for i in range(24)]]:
        store.append_message(role="user", content=text, input_mode="text", session_id="game")
        store.append_message(role="assistant", content="Синоним.", input_mode="text", session_id="game")
    current, _ = store.append_message(role="user", content="Ирис", input_mode="text", session_id="game")
    built = ContextManager(store, recent_turns=2).build("Ирис", session_id="game", current_message_id=current.id)
    assert frame_from_context(built.messages).single_word
    assert built.diagnostics["retrieval_scope"] == "core_and_session"
    assert infer_dialogue_pacing("Ирис", built.messages).mode == "constrained"
    other, _ = store.append_message(role="user", content="Привет", input_mode="text", session_id="new")
    fresh = ContextManager(store).build("Привет", session_id="new", current_message_id=other.id)
    assert not frame_from_context(fresh.messages).active
    assert not any(m.role == "user" and m.content.startswith("слово") for m in fresh.messages)
    assert not any("Текущая задача" in m.content or "слово23" in m.content for m in fresh.messages)


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_both_generation_paths_apply_game_contract_without_extra_calls(tmp_path, live):
    store = TimelineStore(tmp_path / "timeline.db")
    store.init_db()
    for text in GAME:
        store.append_message(role="user", content=text, input_mode="text", session_id="s")
        store.append_message(role="assistant", content="Приняла.", input_mode="text", session_id="s")
    reply = "Касатик."
    class Provider(ReplayLLM):
        async def generate(self, messages):
            self.purpose = current_llm_call_purpose()
            return await super().generate(messages)
    provider = Provider([reply if live else json.dumps({"reply": reply, "emotion": "neutral", "intent": "casual_chat"})])
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), 20, context_manager=ContextManager(store))
    result = "".join([p async for p in agent.stream_user_message("s", "Ирис", input_mode="voice")]) if live else (await agent.handle_user_message("s", "Ирис"))["reply"]
    assert result == reply
    assert len(provider.calls) == 1
    assert provider.purpose == "chat_task"
    prompt = "\n".join(m.content for m in provider.calls[0])
    assert prompt.count(TASK_PREFIX) == 1
    assert "Коротко отзовись" not in prompt
    assert "Разнообразие речи" not in prompt


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("second,expected", [("Детонация.", "Детонация."), ("Тут нужен другой ответ.", "Затрудняюсь.")])
async def test_format_repair_is_bounded_and_bad_draft_never_enters_history(tmp_path, live, second, expected):
    store = TimelineStore(tmp_path / "timeline.db")
    store.init_db()
    for text in GAME:
        store.append_message(role="user", content=text, input_mode="text", session_id="s")
        store.append_message(role="assistant", content="Приняла.", input_mode="text", session_id="s")
    drafts = ["Взрыв — бабах. В смысле, рвануло.", second]
    provider = ReplayLLM(drafts if live else [json.dumps({"reply":r, "emotion":"neutral", "intent":"casual_chat"}) for r in drafts])
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), 20, context_manager=ContextManager(store))
    reply = "".join([s async for s in agent.stream_user_message("s", "взрыв")]) if live else (await agent.handle_user_message("s", "взрыв"))["reply"]
    assert reply == expected
    assert len(provider.calls) == 2
    saved = [r.content for r in store.get_recent_messages("s", 100) if r.role == "assistant"]
    assert drafts[0] not in saved


@pytest.mark.parametrize("text,kind", [
    ("Это мой любимый исполнитель и трек", "preference"),
    ("Мне это нравится", "preference"), ("Я обиделся", "discomfort"),
    ("Хватит подкалывать мой вкус", "stop"), ("Я обиделся, ахаха", ""),
    ('Он сказал «мне это нравится»', ""), ("Прожарь мой вкус, ебать", ""),
    ("Это мой любимый трек, прожарь мой вкус", ""),
])
def test_feedback_distinguishes_preference_discomfort_and_requested_roast(text, kind):
    assert user_feedback(text) == kind
    if kind in {"preference", "discomfort"}:
        cue = feedback_prompt(text)
        assert "Можешь резко" in cue
        assert "не обязана хвалить или извиняться" in cue


@pytest.mark.anyio
@pytest.mark.parametrize("text,expected", [("Я обиделся", "user_frustration"), ("Мой любимый трек", "neutral"), ("Прожарь меня", "teasing")])
async def test_adjudicator_does_not_reward_feedback_as_playful_success(text, expected):
    decision = ConversationDecision(action=ConversationAction.RESPOND, reason=DecisionReason.DIRECT_ADDRESS,
                                    confidence=.9, addressedness=.9, relevance=.8, significance=.4)
    class Provider:
        calls = 0
        async def generate_structured(self, messages, **kwargs):
            self.calls += 1
            return LLMResponse(model="fixture", content=json.dumps({
                "version": 1, "decision": decision.model_dump(mode="json"),
                "appraisal": {"event_kind": "teasing", "emotion_impulses": {"playfulness": .6, "joy": .35}},
            }))
    provider = Provider()
    result = await StructuredConversationAdjudicator(provider).adjudicate(text, fallback_decision=decision,
        fallback_appraisal=EventAppraisal(), cause_message_id="m", speaker_role="primary")
    assert result.appraisal.event_kind == expected
    assert result.dialogue_style is None
    assert result.decision.action == ConversationAction.RESPOND
    assert provider.calls == 1
    if expected != "teasing":
        assert result.appraisal.emotion_impulses == {}


def test_style_honors_task_and_humor_without_turning_down_street():
    base = dialogue_style_prompt("street")
    focused = dialogue_style_prompt("street", turn_mode="focused")
    no_joke = dialogue_style_prompt("street", humor_policy="avoid")
    assert base != focused != no_joke
    assert "мат" in no_joke and "собственное мнение сохраняются" in no_joke
    assert len(base) < 800
    assert "пояснений сверх" in dialogue_style_prompt("street", turn_mode="constrained")


def test_temporary_game_format_cannot_replace_global_response_preference(tmp_path):
    store = TimelineStore(tmp_path / "memory.db")
    store.init_db()
    service = MemoryService(store, RuntimeSettings(), llm_extraction_enabled=True)
    write(store, service, "Я предпочитаю короткие ответы", "prefers_response_length", "короткие ответы")
    for text in GAME:
        store.append_message(role="user", content=text, input_mode="text")
    write(store, service, "Так отвечай одним словом пожалуйста", "prefers_response_length", "Просит отвечать одним словом")
    assert [m["value_text"] for m in store.memory_slot_items("user.prefers_response_length")] == ["короткие ответы"]


def test_conditional_preference_coexists_with_global_profile(tmp_path):
    store = TimelineStore(tmp_path / "memory.db")
    store.init_db()
    service = MemoryService(store, RuntimeSettings(), llm_extraction_enabled=True)
    write(store, service, "Я предпочитаю короткие ответы", "prefers_response_length", "короткие ответы")
    write(store, service, "При разборе кода предпочитаю подробные ответы", "prefers_response_length", "При разборе кода предпочитает подробные ответы")
    assert [m["value_text"] for m in store.memory_slot_items("user.prefers_response_length")] == ["короткие ответы"]
    assert any("При разборе кода" in m["value_text"] for m in store.memory_slot_items("user.preference"))


@pytest.mark.parametrize("protected", [False, True])
def test_scope_repair_is_idempotent_and_preserves_user_actions_and_audit(tmp_path, protected):
    store = TimelineStore(tmp_path / "memory.db")
    store.init_db()
    service = MemoryService(store, RuntimeSettings())
    source, _ = store.append_message(role="user", content="Предпочитаю короткие ответы", input_mode="text")
    old = store.create_memory({"subject":"user", "scope":"user_profile", "kind":"preference", "predicate":"prefers_response_length",
        "slot_key":"user.prefers_response_length", "object_key":"user", "value_text":"короткие ответы", "status":"superseded",
        "source_message_ids":[source.id]}, actor="extractor")
    game = store.create_memory({"subject":"user", "scope":"user_profile", "kind":"preference", "predicate":"prefers_response_length",
        "slot_key":"user.prefers_response_length", "object_key":"user", "value_text":"При игре в синонимы отвечать одним словом",
        "supersedes_id":old["id"], "user_locked":protected}, actor="extractor")
    store.supersede_memory(old["id"], game["id"])
    first = service.repair_task_scoped_preferences()
    second = service.repair_task_scoped_preferences()
    assert second == {"task_rules_removed_from_profile":0, "global_preferences_restored":0}
    assert store.get_memory(game["id"]) is not None
    assert store.get_memory(game["id"])["status"] == ("active" if protected else "rejected")
    assert store.get_memory(old["id"])["status"] == ("superseded" if protected else "active")
    assert first["global_preferences_restored"] == (0 if protected else 1)
    assert store.memory_audit(game["id"])


@pytest.mark.anyio
async def test_body_capability_stays_available_without_irrelevant_pose_report():
    avatar = SimpleNamespace(body_status=AsyncMock(return_value={"connected":True}))
    provider = ReplayLLM([json.dumps({"reply":"Заебись.", "emotion":"neutral", "intent":"casual_chat"})])
    agent = CharacterAgent(provider, History(), 20, avatar_service=avatar)
    await agent.handle_user_message("s", "Как дела?")
    avatar.body_status.assert_not_awaited()
    assert "avatar_body" in [tool["function"]["name"] for tool in agent._skills.tools()]
    assert CharacterAgent._needs_body_context("Помаши левой рукой")


@pytest.mark.parametrize("line", ["Поиск у меня отвалился", "Поиск сломался", "Поиск сейчас не работает"])
def test_invalid_tool_call_cannot_be_reported_as_service_outage(line):
    agent = CharacterAgent(None, History(), 20)
    agent._search_user_text = "Найди песню"
    agent.last_skill_metadata = {"name":"", "status":"invalid"}
    result = agent._truthful_search_reply(line)
    assert result != line and "корректный вызов" in result


def test_literal_query_replacement_discards_assistant_hypotheses():
    old = 'Toyota Yaris монтаж "voice of the lord"'
    edited = explicit_query_revision("Нет, просто найди машина Toyota Yaris сжимается вверх вниз", old)
    assert edited and edited.force_refresh
    assert "lord" not in edited.query and "монтаж" not in edited.query
    followup = explicit_query_revision("Ты вот это вот и дальше то что просто популярная песня Toyota Yaris сжимается вверх вниз всё", old,
        user_messages(["Можешь ещё раз поискать, убери монтаж и voice of the lord"]))
    assert followup and "lord" not in followup.query and "всё" not in followup.query
    assert explicit_query_revision("Не ищи, просто найди машину", old) is None


def test_important_but_unrelated_memory_cannot_outrank_relevance(tmp_path):
    store = TimelineStore(tmp_path / "memory.db")
    store.init_db()
    service = MemoryService(store, RuntimeSettings())
    memory = store.create_memory({"subject":"user", "scope":"user_profile", "kind":"fact", "predicate":"personal_fact",
        "value_text":"Старое важное событие", "importance":1, "confidence":1}, actor="extractor")
    assert service._attach_retrieval([memory], {}, {memory["id"]:.05}, False) == []
    assert service._attach_retrieval([memory], {memory["id"]:1}, {}, False)
