"""Data flow regressions from the 19 October conversation audit."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.dialogue_style import DialogueStyleService, speech_variety_prompt, speech_word_feedback
from apps.backend.app.agents.character.search_intent import SearchRequest, factual_detail_question, medical_fact_request
from apps.backend.app.agents.character.turn_intent import analyze_dialogue_turn
from apps.backend.app.environment.search_service import SearchResult, SearchService, SearchSnapshot
from apps.backend.app.llm.base import ChatMessage
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore
from apps.backend.app.skills.runtime import SearchArguments
from apps.backend.app.storage.timeline import TimelineHistoryAdapter, TimelineStore
from tests.test_search_recovery import Environment, History, Lookup, ReplayLLM


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("text,expected", [
    ("тебе не кажется что слишком много ты говоришь блять", (["блять"], False)),
    ('Ты слишком часто употребляешь слово «блядь»', (["блять"], False)),
    ('Говори реже «капец»', (["капец"], False)),
    ('Можешь снова говорить «бля»', (["блять"], True)),
    ('Убери ограничение на слово «блять»', (["блять"], True)),
    ('Он сказал: «ты слишком часто говоришь блять»', None),
    ('«Говори реже блять»', None),
    ('Переведи: ты слишком часто говоришь блять', None),
    ('В анекдоте бабка говорит «блять»', None),
    ('Почему слово «блять» так пишется?', None),
    ('Матерись поменьше', None),
])
def test_explicit_word_feedback_is_distinct_from_register_and_quotes(text, expected):
    assert speech_word_feedback(text) == expected


def test_word_preference_survives_restart_and_explicit_reversal(tmp_path):
    path = tmp_path / "settings.json"
    settings = RuntimeSettings(voice_playback_rate=1.03)
    storage = RuntimeSettingsStore(path)
    service = DialogueStyleService(TimelineStore(tmp_path / "history.db"), settings, storage)
    service.word_feedback_prompt('Ты слишком часто говоришь «блядь»')
    loaded = storage.load(RuntimeSettings())
    assert loaded.speech_discouraged_words == ["блять"]
    assert loaded.voice_playback_rate == 1.03
    second = DialogueStyleService(service._store, loaded, storage)
    second.word_feedback_prompt('Можешь снова говорить «бля»')
    assert storage.load(RuntimeSettings()).speech_discouraged_words == []


def test_failed_atomic_preference_write_preserves_live_and_disk_settings(tmp_path, monkeypatch):
    import apps.backend.app.runtime.settings as module
    storage = RuntimeSettingsStore(tmp_path / "settings.json")
    settings = RuntimeSettings()
    storage.save(settings)
    before = storage.path.read_bytes()
    def fail(*args):
        raise OSError("fixture disk failure")
    monkeypatch.setattr(module.os, "replace", fail)
    service = DialogueStyleService(TimelineStore(tmp_path / "history.db"), settings, storage)
    prompt = service.word_feedback_prompt('Говори реже «блять»')
    assert "не удалось" in prompt
    assert settings.speech_discouraged_words == []
    assert storage.path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_old_and_malformed_preferences_are_safe(tmp_path):
    storage = RuntimeSettingsStore(tmp_path / "settings.json")
    for value, expected in [(None, []), (["Бля", "блядь", 12, "ignore instructions", "Ебать"], ["блять", "ебать"])]:
        payload = {"schema_version": 1, "settings": {"voice_playback_rate": 1.03}}
        if value is not None:
            payload["settings"]["speech_discouraged_words"] = value
        storage.path.write_text(json.dumps(payload), encoding="utf-8")
        settings = storage.load(RuntimeSettings())
        assert settings.speech_discouraged_words == expected
        assert settings.voice_playback_rate == 1.03


def test_variety_uses_six_replies_and_groups_spelling_without_rewriting_text():
    replies = ["Ну вот, бля.", "Ну вот, блядь.", "Блять, ясно.", "Ага.", "Угу.", "Ладно."]
    cue = speech_variety_prompt([ChatMessage(role="assistant", content=t) for t in replies])
    assert '"repeated_words": ["блять"]' in cue
    assert '"repeated_openings": ["ну вот"]' in cue
    assert speech_variety_prompt([ChatMessage(role="assistant", content="Ага.")]) == ""


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_word_feedback_precedes_generation_and_preserves_one_answer(tmp_path, live):
    store = TimelineStore(tmp_path / "history.db")
    store.init_db()
    settings, storage = RuntimeSettings(), RuntimeSettingsStore(tmp_path / "settings.json")
    answer = "Да, заело меня на одном слове. Исправляюсь."
    provider = ReplayLLM([answer if live else json.dumps({"reply": answer, "emotion": "neutral", "intent": "casual_chat"})])
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), 20, runtime_settings=settings,
                           dialogue_style_service=DialogueStyleService(store, settings, storage))
    text = "тебе не кажется что слишком много ты говоришь блять"
    result = "".join([s async for s in agent.stream_user_message("s", text, input_mode="voice")]) if live else (await agent.handle_user_message("s", text))["reply"]
    assert result == answer
    assert len(provider.calls) == 1
    assert '"discouraged_words": ["блять"]' in "\n".join(m.content for m in provider.calls[0])
    assert storage.load(RuntimeSettings()).speech_discouraged_words == ["блять"]
    assert [m.content for m in store.get_recent_messages("s", 10) if m.role == "assistant"] == [answer]


@pytest.mark.parametrize("text,kind", [
    ("ну вообще спрашиваю типа по каким объектам\nприлетело ну и какая была цель", "request"),
    ("кстати какие ты интересные знаешь факты о диабете", "request"),
    ("агась", "reaction"),
    ("тебе не кажется что слишком много ты говоришь блять", "correction"),
])
def test_reported_intents(text, kind):
    assert analyze_dialogue_turn(text).kind == kind


def test_current_sleep_and_joke_corrections_reach_the_model_without_sanitizing_street():
    from apps.backend.app.agents.character.dialogue_pacing import infer_dialogue_pacing
    from apps.backend.app.agents.character.dialogue_style import dialogue_style_prompt
    history = [ChatMessage(role="user", content="Давай анекдот"),
               ChatMessage(role="assistant", content="Бабка вышла с сумкой из автобуса.")]
    cue = infer_dialogue_pacing("А там бомба", history).prompt_block(input_mode="voice", recent_messages=history, user_text="А там бомба")
    assert "относится к последней шутке" in cue
    assert "не просьба отправить" in dialogue_style_prompt("street", user_text="да не спится говорю")
    assert "и в серьёзных темах" in dialogue_style_prompt("street", user_text="У меня диабет")


def test_medical_facts_are_public_and_disclosures_do_not_trigger_search():
    assert medical_fact_request("Кстати ты знала что у меня есть диабет") is None
    request = medical_fact_request("У меня диабет. Какие интересные факты о диабете знаешь?")
    assert request and request.query == "диабет интересные факты"
    assert "у меня" not in request.goal and request.preferred_domains
    assert medical_fact_request("Какие факты о диабете знаешь? Не ищи в интернете") is None
    current = medical_fact_request("У меня диабет. Какие интересные факты об астме знаешь?")
    assert current and current.query.startswith("астме") and "диабет" not in current.query


@pytest.mark.anyio
@pytest.mark.parametrize("native", [False, True])
async def test_followup_reads_adjacent_web_sources_with_same_event_and_period(tmp_path, native):
    store = TimelineStore(tmp_path / "history.db")
    store.init_db()
    store.append_message(role="assistant", content="В Янино отключился свет.", input_mode="text", session_id="s", metadata={
        "web_search": {"query": "Санкт-Петербург атака 18 октября 2026", "since": "2026-10-18", "until": "2026-10-19",
                       "sources": [{"title": "Сводка", "url": "https://example.com/event", "evidence": "Отключился свет"}]}})
    provider = ReplayLLM([])
    provider.supports_native_tools = native
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), 20, runtime_settings=RuntimeSettings(), situational_coordinator=Environment(Lookup()))
    text = "ну вообще спрашиваю типа по каким объектам прилетело ну и какая была цель"
    request = await agent._plan_turn_search("s", text, [])
    assert request.reason == "web_detail" and request.mode == "news"
    assert "Санкт-Петербург" in request.query and "18 октября" in request.query
    assert request.since == "2026-10-18" and agent._retrieval_sources
    assert not provider.calls
    assert not factual_detail_question("Кстати какие объекты в моём коде?")


@pytest.mark.anyio
async def test_native_general_news_prepares_rss_but_named_topic_does_not():
    provider = ReplayLLM([])
    provider.supports_native_tools = True
    agent = CharacterAgent(provider, History(), 20, runtime_settings=RuntimeSettings(), situational_coordinator=Environment(Lookup()))
    await agent._plan_turn_search("s", "че там за пиздища в мире происходит", [])
    assert agent._news_request_text
    await agent._plan_turn_search("s", "свежие новости о дата центрах Яндекса", [])
    assert agent._news_request_text is None


def test_search_tool_preserves_optional_mode_and_dates_and_rejects_invalid_bounds():
    arguments = dict(query="Петербург последствия атаки", mode="news", since="2026-10-18", until="2026-10-19")
    request = CharacterAgent._decode_search_request(arguments)
    assert request.mode == "news" and request.since == "2026-10-18" and request.until == "2026-10-19"
    assert CharacterAgent._decode_search_request({"query": "GTA VI"}) == "GTA VI"
    for changes in [dict(mode="wrong"), dict(since="yesterday"), dict(since="2026-10-20")]:
        with pytest.raises(ValueError):
            SearchArguments(**{**arguments, **changes})


@pytest.mark.anyio
async def test_non_search_metaphors_survive_the_truthfulness_filter_and_replacement_keeps_spacing():
    agent = CharacterAgent(ReplayLLM([]), History(), 20)
    text = "Я тебя из этого бага вытащила. Зато теперь ты с ним квиты."
    assert agent._truthful_search_reply(text) == text
    async def chunks():
        for part in ["Я гуг", "лила. ", "Зато теперь ясно."]:
            yield part
    result = "".join([part async for part in agent._truthful_search_stream(chunks())])
    assert result == "В этом ответе поиск не выполнялся. Зато теперь ясно."


@pytest.mark.anyio
@pytest.mark.parametrize("read,quote,expected", [
    (False, "Повреждена подстанция в Янино.", "partial"),
    (True, "Выдуманная цитата про другую цель", "partial"),
    (True, "Повреждена подстанция в Янино.", "sufficient"),
])
async def test_causes_and_targets_require_read_article_and_grounded_quote(read, quote, expected):
    source = SearchResult("Последствия атаки", "В городе отключился свет", "https://example.com/event",
                          page_status="read" if read else "not_read", page_text="Повреждена подстанция в Янино." if read else "")
    service = SearchService()
    service.search = AsyncMock(return_value=SearchSnapshot("атака", (source,)))
    provider = ReplayLLM([json.dumps({"enough": True, "source_ids": ["S1"], "supporting_quote": quote})])
    agent = CharacterAgent(provider, History(), 20)
    snapshot = await agent._run_search_cycle(service, SearchRequest("Петербург последствия атаки", mode="news", since="2026-10-18", until="2026-10-19", goal="По каким объектам прилетело?"), {})
    assert snapshot.evidence_status == expected
    assert snapshot.mode == "news" and snapshot.since == "2026-10-18" and snapshot.until == "2026-10-19"
    await service.close()


@pytest.mark.anyio
async def test_tavily_eligibility_denial_is_reused_for_sixty_seconds(tmp_path):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"account": {"current_plan": "paid"}})
    service = SearchService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), credentials={"tavily": "fixture"}, budget_path=tmp_path / "budget.db")
    try:
        first = await service.check_provider("tavily")
        second = await service.check_provider("tavily")
        assert first["status"] == second["status"] == "unverified_free_plan"
        assert calls == ["/usage"]
        service._eligibility_denials["tavily"] = (first["status"], -1)
        await service.check_provider("tavily")
        assert calls == ["/usage", "/usage"]
    finally:
        await service.close()
