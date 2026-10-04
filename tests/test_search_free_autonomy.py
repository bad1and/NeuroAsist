"""Conversational search, evidence, and strict free-tier regressions."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
import sqlite3
import time

import httpx
import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.search_intent import plan_search, needs_query_planner
from apps.backend.app.environment.retrieval import relevance
from apps.backend.app.environment.search_budget import SearchBudget
from apps.backend.app.environment.search_service import SearchService, SearchResult, SearchTurnBudget
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore
from apps.backend.app.storage.timeline import TimelineStore, TimelineHistoryAdapter
from tests.test_search_recovery import ReplayLLM, History, Environment, messages


@pytest.fixture
def anyio_backend():
    return "asyncio"


def free_usage(used=0):
    return {"account": {"current_plan": "Researcher", "plan_usage": used, "plan_limit": 1000,
                        "paygo_usage": 0, "paygo_limit": 0}, "key": {"usage": used, "limit": 1000}}


def test_pasted_music_dialogue_and_topic_boundaries():
    context = messages("знаешь ли ты такого исполнителя гон флат")
    first = plan_search("ну это больше рэп можешь поискать в принципе да", context)
    assert first.query == "гон флат" and "принципе" not in first.query
    context += messages("ну это больше рэп можешь поискать в принципе да",
                        "могу сказать трек как один из популярных такой называется трек мамбл",
                        "ну это мой любимый исполнитель")
    retry = plan_search("попробуй еще раз найти", context)
    assert retry.query == "гон флат мамбл" and retry.force_refresh
    bio = plan_search("ну можешь вообще почитать подробнее его как сказать то географию хотел сказать биографию можешь почитать", context)
    assert bio.query == "гон флат биография"
    context += messages("да я просто напевал песню лсп", "да все верно")
    latest = plan_search("какая какая у него там последняя песня выходила", context)
    assert latest.query.casefold() == "лсп последняя песня дата релиза"
    deletion = "угу кстати какие там треки поудаляли на яндекс музыке ну и российских платформах для прослушивания"
    assert "яндекс" in plan_search(deletion).query
    assert "яндекс" in plan_search("давай", messages(deletion)).query
    assert plan_search("давай ка еще раз", messages(deletion, "давай")).force_refresh
    assert plan_search("давай", messages("привет")) is None
    assert plan_search("попробуй еще раз найти", [*context, *messages("не надо")]) is None
    assert plan_search("не ищи в интернете", context) is None
    assert needs_query_planner("почитай о нём", messages("исполнитель с необычным именем"))


def test_action_entity_and_dates_are_not_interchangeable():
    assert plan_search("поищи GONE.Fludd").query == "gonefludd"
    assert plan_search("поищи ЛСП").query == "lsp"
    assert relevance("гон флат мамбл", "GONE.Fludd Мамбл текст песни") > 0
    assert relevance("гон флат мамбл", "Мамбл — музыкальный жанр") == 0
    assert relevance("какие треки удалили с Яндекс Музыки", "Как добавить треки в Яндекс Музыку") == 0
    assert relevance("какие треки удалили с Яндекс Музыки", "Яндекс Музыка удалила треки исполнителя") > 0


def test_durable_atomic_quota_external_spending_and_restart(tmp_path):
    path = tmp_path / "budget.sqlite3"
    budget = SearchBudget(path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: budget.reserve(free_usage(897)), range(8)))
    assert sum(r["status"] == "reserved" for r in results) == 3
    assert SearchBudget(path).reserve(free_usage())["status"] == "quota_exhausted"
    second = SearchBudget(tmp_path / "external.sqlite3")
    assert second.reserve(free_usage(900))["status"] == "quota_exhausted"
    old = SearchBudget(tmp_path / "month.sqlite3")
    assert old.reserve(free_usage())["used"] == 1
    with sqlite3.connect(old.path) as connection:
        connection.execute("UPDATE search_budget SET month='2000-01', used=900")
    assert old.reserve(free_usage())["used"] == 1


def test_pending_reservations_respect_key_limit(tmp_path):
    usage = free_usage()
    usage["key"]["limit"] = 1
    budget = SearchBudget(tmp_path / "key.sqlite3")
    assert budget.reserve(usage)["status"] == "reserved"
    assert budget.reserve(usage)["status"] == "quota_exhausted"


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["paid", "paygo", "missing", "exhausted", "unavailable"])
async def test_no_search_request_without_verified_free_credit(tmp_path, change):
    usage = free_usage(900 if change == "exhausted" else 0)
    if change == "paid":
        usage["account"]["current_plan"] = "Project"
    if change == "paygo":
        usage["account"]["paygo_limit"] = 10
    if change == "missing":
        del usage["account"]["paygo_limit"]
    calls = []
    def handler(request):
        calls.append(request.url.path)
        assert request.url.path == "/usage"
        return httpx.Response(503) if change == "unavailable" else httpx.Response(200, json=usage)
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), credentials={"tavily": "fixture-key"}, budget_path=tmp_path / "budget.sqlite3")
    try:
        result = await service.check_provider("tavily")
        assert result["status"] != "ok" and calls == ["/usage"]
    finally:
        await service.close()


@pytest.mark.anyio
async def test_check_search_timeout_reservation_and_legacy_provider_block(tmp_path):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/usage":
            return httpx.Response(200, json=free_usage())
        assert request.url.path == "/search"
        body = json.loads(request.content)
        assert body["search_depth"] == "basic" and body["auto_parameters"] is False
        raise httpx.ReadTimeout("uncertain", request=request)
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), credentials={"tavily": "fixture-key", "brave": "secret"}, budget_path=tmp_path / "budget.sqlite3")
    try:
        assert (await service.check_provider("brave"))["status"] == "free_only"
        assert not calls
        assert (await service.check_provider("tavily"))["status"] == "timeout"
        assert SearchBudget(service._budget.path).reserve(free_usage())["used"] == 2
        assert calls == ["/usage", "/search"]
    finally:
        await service.close()


class CycleSearch(SearchService):
    def __init__(self):
        super().__init__()
        self.queries = []

    async def search(self, query, **options):
        budget = options["budget"]
        assert budget.admit(query)
        self.queries.append(query)
        options["progress"]("reading")
        return self._snapshot(query, status="empty" if len(self.queries) == 1 else "ok", results=[] if len(self.queries) == 1 else [
            SearchResult("GONE.Fludd — биография", "Исполнитель GONE.Fludd", "https://example.com/artist", page_text="GONE.Fludd — исполнитель. Трек Мамбл.", page_status="read")],
            attempts=({"provider": "fixture", "query": query, "status": "ok", "accepted": 1, "latency_ms": 1},))


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_same_turn_refinement_evidence_and_progress(live):
    llm = ReplayLLM([json.dumps({"enough": False, "query": "GONE.Fludd Мамбл биография"}),
                     json.dumps({"enough": True, "source_ids": ["S1"], "canonical_entity": "GONE.Fludd"}),
                     '[[avatar emotion=neutral gesture=auto intensity=1.0]] Нашла исполнителя GONE.Fludd.' if live else '{"reply":"Нашла исполнителя GONE.Fludd.","emotion":"neutral","intent":"question"}'])
    service = CycleSearch()
    events = []
    agent = CharacterAgent(llm, History(messages("знаешь ли ты такого исполнителя гон флат")), 8,
                           event_publisher=lambda *args: events.append(args), situational_coordinator=Environment(service), runtime_settings=RuntimeSettings())
    if live:
        result = "".join([d async for d in agent.stream_user_message("s", "можешь поискать в принципе да", persist_reply=False)])
    else:
        result = (await agent.handle_user_message("s", "можешь поискать в принципе да", persist_reply=False))["reply"]
    assert "GONE.Fludd" in result and len(service.queries) == 2
    assert agent.last_web_search_metadata["canonical_entity"] == "GONE.Fludd"
    assert agent.last_web_search_metadata["evidence_status"] == "sufficient"
    assert len(agent.last_web_search_metadata["attempts"]) == 2
    assert agent.token_metadata()["total_tokens"] == 36
    assert events[-1][3]["phase"] == "finished"
    assert all(e[3]["session_id"] == "s" for e in events if e[0] == "retrieval.progress")


@pytest.mark.anyio
async def test_provenance_guards_before_speech_and_shared_limits():
    agent = CharacterAgent(ReplayLLM([]), History(), 8)
    agent._turn_search_snapshot = SearchService._snapshot("треки", status="ok", results=[], attempts=({"status": "ok"},))
    assert "дважды" not in agent._truthful_search_reply("Я искала дважды.")
    from dataclasses import replace
    agent._turn_search_snapshot = replace(agent._turn_search_snapshot, attempts=({"status": "ok", "cached": True}, {"status": "ok", "cached": False}))
    assert "дважды" not in agent._truthful_search_reply("Я искала дважды.")
    async def chunks():
        for s in ["Да, я гуг", "лила два раза", ".", " Итог неизвестен."]:
            yield s
    result = "".join([d async for d in agent._truthful_search_stream(chunks())])
    assert "гуглила" not in result and "Итог неизвестен" in result
    budget = SearchTurnBudget(time.monotonic() + 15)
    assert all(budget.admit("same") for _ in range(6))
    assert not budget.admit("same")
    budget = SearchTurnBudget(time.monotonic() + 15)
    assert all(budget.admit(str(i)) for i in range(3))
    assert not budget.admit("fourth")


def test_policy_is_mandatory_after_old_settings_load(tmp_path):
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    settings = RuntimeSettings(web_search_provider="brave", web_search_free_only=False)
    store.save(settings)
    assert store.load(RuntimeSettings()).web_search_free_only is True


@pytest.mark.anyio
async def test_session_state_survives_recreation_and_retry_changes_strategy(tmp_path):
    store = TimelineStore(tmp_path / "history.sqlite3")
    store.init_db()
    previous = SearchService._snapshot("гон флат мамбл", status="empty", attempts=({"query": "гон флат мамбл", "status": "empty"},)).metadata()
    previous["canonical_entity"] = "GONE.Fludd"
    store.append_message(role="assistant", content="Пока не нашла", input_mode="text", session_id="s", metadata={"web_search": previous})
    agent = CharacterAgent(ReplayLLM(['{"query":"GONE.Fludd Мамбл исполнитель"}']), TimelineHistoryAdapter(store), 8,
                           situational_coordinator=Environment(CycleSearch()), runtime_settings=RuntimeSettings())
    request = await agent._plan_turn_search("s", "попробуй еще раз найти", [])
    assert request.query == "GONE.Fludd Мамбл исполнитель" and request.force_refresh
    assert request.reason == "retry_refined"
    bio = await agent._plan_turn_search("s", "почитай о нём", [])
    assert bio.query == "GONE.Fludd биография"
    latest = await agent._plan_turn_search("s", "какая у него последняя песня", [])
    assert latest.query == "GONE.Fludd последняя песня дата релиза"
    assert await agent._plan_turn_search("other", "давай", []) is None
    assert await agent._plan_turn_search("s", "перепиши текст еще раз", []) is None
    assert await agent._plan_turn_search("s", "не ищи в интернете", []) is None


@pytest.mark.anyio
async def test_cancel_clears_progress_without_answer():
    class WaitingSearch(CycleSearch):
        async def search(self, query, **options):
            await asyncio.Event().wait()
    events = []
    agent = CharacterAgent(ReplayLLM([]), History(), 8, event_publisher=lambda *a: events.append(a),
                           situational_coordinator=Environment(WaitingSearch()), runtime_settings=RuntimeSettings())
    agent._search_session_id = "s"
    task = asyncio.create_task(agent._perform_web_search("artist biography"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events[-1][3]["phase"] == "finished"
    assert agent.last_web_search_metadata is None
