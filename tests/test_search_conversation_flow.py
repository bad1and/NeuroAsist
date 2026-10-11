"""Search, speech races and document evidence from the reported conversation."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.search_intent import plan_search
from apps.backend.app.environment.search_service import SearchResult, SearchService, SearchSnapshot, SearchTurnBudget, _ArticleParser
from apps.backend.app.llm.base import ChatMessage, LLMResponse, LLMUsage
from apps.backend.app.llm.metadata import token_metadata
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore
from tests.test_search_recovery import History, ReplayLLM, Environment, Lookup


def test_leading_search_command_with_extra_prose_preserves_query():
    requested, query = CharacterAgent._live_web_search_request(
        '[[web_search: {"query":"дроны над Россией свежие сводки"}]]\nСейчас гляну.'
    )
    assert requested and query == "дроны над Россией свежие сводки"
    assert CharacterAgent._live_web_search_request('[[web_search: {\n"query":"дроны над Россией"\n}]]')[1] == "дроны над Россией"
    assert CharacterAgent._live_web_search_request("[[web_search query missing separator]]") == (True, None)


def test_acceptance_of_unresolved_lookup_offer_uses_query_planner():
    from apps.backend.app.agents.character.search_intent import needs_query_planner
    context = [ChatMessage(role="user", content="Дроны над Россией называют комарами"),
               ChatMessage(role="assistant", content="Хочешь, гляну, что сейчас по сводкам?")]
    assert needs_query_planner("давай", context)
    assert not needs_query_planner("ага", [ChatMessage(role="assistant", content="Понятно.")])


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("question", ["почему ты до этого говорила то что не могла искать", "а ты пиздишь запроса не было от тебя"])
async def test_search_process_challenge_uses_audit_without_lookup(live, question):
    class AuditHistory(History):
        def get_recent_search_operations(self, _session):
            return [{"status": "invalid", "cached": False}, {"status": "invalid", "cached": False},
                    {"status": "ok", "cached": False, "attempts": [{"status": "ok", "searched": True}]},
                    {"status": "ok", "cached": True, "attempts": [{"status": "ok", "searched": True, "cached": True}]}]
        def get_recent_retrieval_state(self, _session):
            return {"web_search": {"query": "дроны над Россией", "status": "ok"}}
    false = "Не пизжу. Три раза отправляла — два вернулись пустыми, третий дал сводку."
    llm = ReplayLLM([false if live else json.dumps({"reply": false, "emotion": "neutral", "intent": "question"}, ensure_ascii=False)])
    lookup = Lookup()
    agent = CharacterAgent(llm, AuditHistory(), 10, situational_coordinator=Environment(lookup), runtime_settings=RuntimeSettings())
    if live:
        answer = "".join([part async for part in agent.stream_user_message("s", question, persist_reply=False)])
    else:
        answer = (await agent.handle_user_message("s", question, persist_reply=False))["reply"]
    assert not lookup.calls and agent.last_web_search_metadata is None
    assert "Три раза" not in answer and "Не пизжу" not in answer
    assert "не был отправлен" in answer
    assert any('"network_calls": 0' in m.content and '"network_calls": 1' in m.content for m in llm.calls[-1] if m.role == "system")


def test_invalid_query_cannot_be_described_as_service_outage():
    agent = CharacterAgent(ReplayLLM([]), History(), 10)
    assert agent._truthful_search_reply("Поиск сейчас не отвечает.") == "В этом ответе поиск не выполнялся."
    rules = agent._web_search_followup(None, live=True, status_hint="invalid")
    assert "Это не сбой поисковика" in rules
    assert agent._required_response_anchors("почему ты до этого говорила то что не могла искать") == []
    assert agent._required_response_anchors("не Маша, а Даша") == ["даша"]


def test_search_operation_audit_is_bounded_and_session_local(tmp_path):
    from apps.backend.app.storage.timeline import TimelineStore, TimelineHistoryAdapter
    store = TimelineStore(tmp_path / "audit.sqlite3"); store.init_db()
    store.append_message(role="assistant", content="Чужой ход", input_mode="text", session_id="other", metadata={"web_search": {"status": "timeout"}})
    store.append_message(role="assistant", content="Не отвечает", input_mode="voice", session_id="s", metadata={"web_search": {"status": "invalid", "query": "", "cached": False}})
    store.append_message(role="assistant", content="Другая реплика", input_mode="text", session_id="s")
    operations = TimelineHistoryAdapter(store).get_recent_search_operations("s")
    assert operations == [{"query": "", "status": "invalid", "cached": False}]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_notifications_default_and_restart(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    store.path.write_text('{"schema_version":1,"settings":{"web_search_enabled":true}}', encoding="utf-8")
    runtime = store.load(RuntimeSettings())
    assert runtime.web_search_enabled and not runtime.web_search_notifications_enabled
    runtime.web_search_notifications_enabled = True
    store.save(runtime)
    assert RuntimeSettingsStore(store.path).load(RuntimeSettings()).web_search_notifications_enabled


def test_ordered_div_pre_breaks_and_description_is_not_full_content():
    parser = _ArticleParser()
    parser.feed('<main><div><h1>Документ Альфа</h1><div>Первая строка документа<br>Вторая строка документа<br>Третья строка документа</div><pre>Четвертая строка\nПятая строка</pre></div></main>')
    text, _ = parser.evidence("Альфа третья строка")
    assert text.index("Первая") < text.index("Вторая") < text.index("Третья") < text.index("Четвертая")
    assert "\n" in text and not parser.used_description
    parser = _ArticleParser(); parser.feed('<meta name="description" content="Есть только описание документа Альфа">')
    assert parser.evidence("Альфа")[0] and parser.used_description


def test_document_budget_keeps_target_beyond_old_600_characters():
    document = "Начало документа Альфа. " * 35 + "ИСКОМАЯ ДЕТАЛЬ В КОНЦЕ."
    snap = SearchSnapshot("Документ Альфа", (SearchResult("Документ Альфа", "", "https://example.org/alpha", page_text=document, page_status="read"),))
    assert "ИСКОМАЯ ДЕТАЛЬ" in snap.compact_summary(max_chars=2400)
    assert "ИСКОМАЯ ДЕТАЛЬ" in snap.metadata()["sources"][0]["evidence"]


def test_context_window_prefers_requested_fragment_and_marks_truncation():
    document = "Вступительная строка.\n" * 150 + "Второй куплет\nИскомая строка номер два\nПродолжение куплета\n" + "Окончание документа.\n" * 80
    parser = _ArticleParser(); parser.feed("<pre>" + document + "</pre>")
    evidence, _ = parser.evidence("второй куплет")
    assert "Искомая строка номер два" in evidence and parser.content_truncated
    snapshot = SearchSnapshot("Альфа", (SearchResult("Альфа", "", "https://example.org/alpha", page_text=document, page_status="read", content_truncated=True),), requested_fact="Покажи второй куплет")
    summary = snapshot.compact_summary(max_chars=1600)
    assert "Искомая строка номер два" in summary and "полнота не подтверждена" in summary
    assert "Искомая строка номер два" in snapshot.metadata()["sources"][0]["evidence"]


def test_named_material_request_preserves_noisy_title_and_does_not_search_supplied_body():
    request = plan_search("можешь спеть песню раз раз раз это харбас")
    assert request and request.entity == "раз раз раз это хардбасс" and "текст" in request.query
    body = "[Куплет 1]\n" + "Пользовательская строка для исполнения.\n" * 8
    assert plan_search(body) is None
    assert plan_search("Вот текст, спой его: " + "Пользовательская строка. " * 12) is None
    assert plan_search("спой это без интернета") is None


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_supplied_material_uses_input_without_search_or_false_lookup_claim(live):
    body = "[Куплет 1]\n" + "Пользовательская строка для исполнения.\n" * 8
    response = "По твоему тексту: пользовательская строка."
    llm = ReplayLLM([response if live else json.dumps({"reply": response, "emotion": "neutral", "intent": "casual_chat"}, ensure_ascii=False)])
    lookup = Lookup()
    agent = CharacterAgent(llm, History(), 10, situational_coordinator=Environment(lookup), runtime_settings=RuntimeSettings())
    if live:
        answer = "".join([part async for part in agent.stream_user_message("s", body, persist_reply=False)])
    else:
        answer = (await agent.handle_user_message("s", body, persist_reply=False))["reply"]
    assert answer == response and not lookup.calls
    assert any("готовый материал" in m.content for m in llm.calls[-1] if m.role == "system")


@pytest.mark.anyio
async def test_continuation_uses_selected_source_but_provided_material_stays_local():
    class SourceHistory(History):
        def get_recent_retrieval_state(self, _session):
            return {"web_search": {"query": "Песня Альфа текст", "canonical_entity": "Альфа", "sources": [
                {"title": "Альфа", "url": "https://example.org/alpha", "evidence": "Первый фрагмент"}]}}
    service = SearchService()
    service.read_sources = AsyncMock(return_value=SearchSnapshot("Альфа", (SearchResult("Альфа", "", "https://example.org/alpha", page_text="Второй куплет из выбранного документа.", page_status="read"),)))
    service.search = AsyncMock()
    agent = CharacterAgent(ReplayLLM(['{"enough":false,"query":""}']), SourceHistory(), 10,
                           situational_coordinator=Environment(service), runtime_settings=RuntimeSettings())
    try:
        request = await agent._plan_turn_search("s", "продолжай", [ChatMessage(role="user", content="Спой песню Альфа")])
        assert request.reason == "material_detail" and request.entity == "Альфа"
        await agent._perform_web_search(request)
        service.read_sources.assert_awaited_once()
        service.search.assert_not_awaited()
        body = "Вот текст:\n" + "Пользовательская строка для исполнения.\n" * 8
        assert await agent._plan_turn_search("s", "продолжай", [ChatMessage(role="user", content=body)]) is None
        assert agent._turn_lookup_suppressed and "готовый материал" in agent._no_lookup_rule()
        assert await agent._plan_turn_search("s", "ага", [ChatMessage(role="user", content="Спой Альфа")]) is None
    finally:
        await service.close()


@pytest.mark.anyio
async def test_result_beats_bridge_and_cancels_its_generation(monkeypatch):
    monkeypatch.setattr("apps.backend.app.agents.character.agent._SEARCH_ACK_DELAY_SECONDS", .001)
    entered, cancelled = asyncio.Event(), asyncio.Event()
    class SlowBridge(ReplayLLM):
        async def generate(self, messages):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
    agent = CharacterAgent(SlowBridge([]), History(), 10)
    async def lookup():
        await entered.wait()
        return "evidence"
    parts = [p async for p in agent._wait_for_lookup(lookup(), acknowledge=True)]
    assert parts == [("", "evidence")] and cancelled.is_set() and not agent._search_acknowledged


@pytest.mark.anyio
async def test_bad_bridge_does_not_break_lookup_and_no_retry(monkeypatch):
    monkeypatch.setattr("apps.backend.app.agents.character.agent._SEARCH_ACK_DELAY_SECONDS", .001)
    llm = ReplayLLM(['{"reply":"Нашла новую дату."}'])
    agent = CharacterAgent(llm, History(), 10)
    async def lookup():
        await asyncio.sleep(.015)
        return "evidence"
    assert [p async for p in agent._wait_for_lookup(lookup(), acknowledge=True)] == [("", "evidence")]
    assert len(llm.calls) == 1 and agent.web_search_usage_metadata["total_tokens"] == 12


@pytest.mark.anyio
async def test_planner_bridge_is_reused_without_standalone_model_call(monkeypatch):
    monkeypatch.setattr("apps.backend.app.agents.character.agent._SEARCH_ACK_DELAY_SECONDS", .001)
    llm = ReplayLLM([]); agent = CharacterAgent(llm, History(), 10)
    agent._planned_bridge = "С названием понятно, а вот детали…"
    async def lookup():
        await asyncio.sleep(.015)
        return "evidence"
    parts = [p async for p in agent._wait_for_lookup(lookup(), acknowledge=True)]
    assert "С названием" in parts[0][0] and parts[-1] == ("", "evidence") and not llm.calls


@pytest.mark.anyio
async def test_sufficiency_covers_original_request_and_rejects_foreign_song():
    service = SearchService()
    service.search = AsyncMock(return_value=SearchSnapshot("Песня Альфа текст", (
        SearchResult("Песня Альфа", "Трек существует", "https://example.org/alpha"),)))
    llm = ReplayLLM(['{"enough":false,"source_ids":["S1"],"query":"Песня Бета текст"}'])
    agent = CharacterAgent(llm, History(), 10, situational_coordinator=Environment(service), runtime_settings=RuntimeSettings())
    agent._search_user_text = "Спой песню Альфа до конца"
    try:
        result = await agent._perform_web_search(plan_search(agent._search_user_text))
        assert result.evidence_status == "partial" and service.search.await_count == 1
        assert "Спой песню Альфа до конца" in llm.calls[0][-1].content
    finally:
        await service.close()


@pytest.mark.anyio
async def test_track_existence_cannot_satisfy_content_request_even_if_model_says_enough():
    service = SearchService()
    service.search = AsyncMock(return_value=SearchSnapshot("Альфа", (
        SearchResult("Альфа", "Есть такой трек", "https://example.org/alpha", page_text="Альфа — название трека.", page_status="read"),)))
    llm = ReplayLLM(['{"enough":true,"source_ids":["S1"]}'])
    agent = CharacterAgent(llm, History(), 10, situational_coordinator=Environment(service), runtime_settings=RuntimeSettings())
    try:
        result = await agent._perform_web_search(plan_search("спой песню Альфа"))
        assert result.evidence_status == "partial"
    finally:
        await service.close()


def test_usage_from_explicit_response_ignores_parallel_last_response():
    llm = ReplayLLM([])
    a = LLMResponse(content="{}", model="fixture", usage=LLMUsage(total_tokens=7))
    llm.last_response = LLMResponse(content="{}", model="fixture", usage=LLMUsage(total_tokens=100))
    assert token_metadata(llm, response=a)["total_tokens"] == 7


@pytest.mark.anyio
async def test_unverified_tavily_is_checked_once_per_shared_cycle():
    import time
    service = SearchService(runtime_settings=RuntimeSettings(web_search_provider="tavily"))
    service._api_provider = AsyncMock(return_value=([], "unverified_free_plan"))
    service._provider = AsyncMock(return_value=([], "empty"))
    budget = SearchTurnBudget(time.monotonic() + 15)
    try:
        await service.search("Документ Альфа", budget=budget)
        await service.search("Документ Альфа текст", budget=budget)
        assert service._api_provider.await_count == 1
        assert service.selected_provider() == "tavily"
    finally:
        await service.close()


@pytest.mark.anyio
async def test_voice_input_cancels_registered_typed_generation(tmp_path):
    from apps.backend.app.conversation.service import LiveConversationService
    from apps.backend.app.conversation.turn_coordinator import ConversationTurnCoordinator
    from apps.backend.app.storage.timeline import TimelineStore
    store = TimelineStore(tmp_path / "timeline.sqlite3"); store.init_db()
    coordinator = ConversationTurnCoordinator(store)
    accepted = await coordinator.accept_user_turn(session_id="s", content="Первый запрос", input_mode="text")
    lease = await coordinator.begin_assistant(accepted)
    task = asyncio.create_task(asyncio.sleep(100))
    coordinator.register_generation_task(lease, task)
    conversation = LiveConversationService(store, RuntimeSettings())
    conversation.bind_turn_coordinator(coordinator)
    await conversation.speech_started("s")
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.get_message(lease.assistant_message_id).status == "interrupted"


@pytest.mark.anyio
async def test_typed_acceptance_atomically_cancels_old_voice_work_and_deduplicates(tmp_path):
    from apps.backend.app.conversation.service import LiveConversationService
    from apps.backend.app.conversation.turn_coordinator import ConversationTurnCoordinator
    from apps.backend.app.storage.timeline import TimelineStore
    store = TimelineStore(tmp_path / "timeline.sqlite3"); store.init_db()
    coordinator = ConversationTurnCoordinator(store)
    conversation = LiveConversationService(store, RuntimeSettings())
    conversation.bind_turn_coordinator(coordinator)
    session = await conversation.ensure_session("s")
    task = conversation._register_task(session, asyncio.sleep(100), name="old-stt", generation=session.generation, reason="test")
    async def supersede():
        await conversation.text_started("s")
    callback = AsyncMock(side_effect=supersede)
    accepted = await coordinator.accept_user_turn(session_id="s", content="Готовый материал", input_mode="text", client_message_id="once", on_created=callback)
    with pytest.raises(asyncio.CancelledError):
        await task
    duplicate = await coordinator.accept_user_turn(session_id="s", content="Готовый материал", input_mode="text", client_message_id="once", on_created=callback)
    assert not duplicate.created and duplicate.user_message_id == accepted.user_message_id
    callback.assert_awaited_once()


@pytest.mark.anyio
async def test_late_audio_interrupt_does_not_cancel_new_typed_reply(tmp_path):
    from apps.backend.app.conversation.turn_coordinator import ConversationTurnCoordinator
    from apps.backend.app.storage.timeline import TimelineStore
    store = TimelineStore(tmp_path / "timeline.sqlite3"); store.init_db()
    coordinator = ConversationTurnCoordinator(store)
    accepted = await coordinator.accept_user_turn(session_id="s", content="Новый вопрос", input_mode="text", utterance_id="new")
    lease = await coordinator.begin_assistant(accepted)
    task = asyncio.create_task(asyncio.sleep(100))
    coordinator.register_generation_task(lease, task)
    await coordinator.cancel_session("s", "old")
    assert not task.cancelled() and store.get_message(lease.assistant_message_id).status == "streaming"
    await coordinator.cancel_session("s", "new")
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_late_task_registration_and_completion_cannot_resurrect_old_lease(tmp_path):
    from apps.backend.app.conversation.turn_coordinator import ConversationTurnCoordinator
    from apps.backend.app.storage.timeline import TimelineStore
    store = TimelineStore(tmp_path / "timeline.sqlite3"); store.init_db()
    coordinator = ConversationTurnCoordinator(store)
    accepted = await coordinator.accept_user_turn(session_id="s", content="Первый", input_mode="text")
    lease = await coordinator.begin_assistant(accepted)
    await coordinator.accept_user_turn(session_id="s", content="Второй", input_mode="text")
    task = asyncio.create_task(asyncio.sleep(100))
    coordinator.register_generation_task(lease, task)
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(asyncio.CancelledError):
        await coordinator.complete_assistant("s", lease, "Устаревший ответ")
    assert store.get_message(lease.assistant_message_id).status == "interrupted"


@pytest.mark.anyio
async def test_voice_owner_check_discards_late_delta_audio_and_completion():
    from apps.backend.app.voice.live import VoiceSessionManager
    from apps.backend.app.voice.providers import MockTTSProvider
    from tests.test_live_voice import FakeVoiceConnection
    started, release = asyncio.Event(), asyncio.Event()
    current = True
    class LateAgent:
        def classify_intent(self, _text):
            return "casual_chat"
        async def stream_user_message(self, *_args, **_kwargs):
            started.set()
            await release.wait()
            yield "Устаревшее продолжение."
    connection = FakeVoiceConnection()
    manager = VoiceSessionManager(MockTTSProvider())
    manager._connections["s"] = connection
    complete = AsyncMock()
    task = await manager.start(session_id="s", utterance_id="u", transcript="Ирис", language="ru", voice="ru_f1",
                               agent=LateAgent(), on_assistant_completed=complete, owner_is_current=lambda: current)
    await asyncio.wait_for(started.wait(), 1)
    current = False
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not connection.segments and not any(e["type"] in {"voice.text.delta", "voice.text.completed"} for e in connection.events)
    complete.assert_not_awaited()


@pytest.mark.anyio
async def test_bridge_provider_has_no_reasoning_96_token_cap_and_no_retry(monkeypatch):
    import httpx
    from openai import APITimeoutError
    from apps.backend.app.llm.base import LLMProviderError
    from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
    from tests.test_deepseek_provider import FakeClient, _settings
    client = FakeClient([APITimeoutError(request=httpx.Request("POST", "https://example.org/fixture"))])
    monkeypatch.setattr(DeepSeekProvider, "_client", property(lambda _self: client))
    provider = DeepSeekProvider(_settings())
    previous = LLMResponse(content="Основной ответ", model="fixture")
    provider._last_response = previous
    bridge = provider.fork_for_purpose("chat_search_bridge")
    with pytest.raises(LLMProviderError):
        await bridge.generate([ChatMessage(role="user", content="Пока ждём")])
    assert provider.last_response is previous
    assert len(client.completions.calls) == 1
    assert client.completions.calls[0]["max_tokens"] == 96
    assert client.completions.calls[0]["extra_body"]["thinking"]["type"] == "disabled"


@pytest.mark.anyio
async def test_late_interrupt_does_not_cancel_a_new_batch_speech_job():
    from types import SimpleNamespace
    from apps.backend.app.voice.orchestrator import SpeechOrchestrator
    orchestrator = SpeechOrchestrator(SimpleNamespace(set_tts_job=lambda *_args: None), None, None, None)
    async def wait(**_kwargs):
        await asyncio.Future()
    orchestrator._run = wait
    orchestrator.enqueue(session_id="s", reply="Новый ответ", emotion="neutral", intent="casual_chat", voice="ru_f1", voice_request_id="new")
    assert await orchestrator.cancel_session("s", "old") == 0
    assert await orchestrator.cancel_session("s", "new") == 1
    await orchestrator.close()


@pytest.mark.anyio
async def test_retry_planner_cannot_replace_the_original_song_and_reuses_bridge():
    class RetryHistory(History):
        def get_recent_retrieval_state(self, _session):
            return {"web_search": {"query": "Альфа текст песни", "canonical_entity": "Альфа",
                                   "attempts": [{"query": "Альфа текст песни", "status": "empty"}]}}
    llm = ReplayLLM(['{"query":"Бета текст песни полностью","reply":"Сверю оставшийся фрагмент."}'])
    agent = CharacterAgent(llm, RetryHistory(), 10, situational_coordinator=Environment(Lookup()), runtime_settings=RuntimeSettings())
    agent._streaming_turn = True
    request = await agent._plan_turn_search("s", "поищи это ещё раз", [ChatMessage(role="user", content="найди песню Альфа текст")])
    assert request and "Альфа" in request.query and "Бета" not in request.query
    assert agent._planned_bridge == "Сверю оставшийся фрагмент."
