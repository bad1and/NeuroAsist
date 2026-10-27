import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.opinions import (
    BASE_STANCE, CONTEXT_CHARS, OpinionConflict, OpinionProposal, OpinionStore, opinion_stream,
)
from apps.backend.app.api.routes.opinions import router
from apps.backend.app.llm.base import ChatMessage, LLMResponse


FIELDS = dict(topic="Кошки", stance="Кошки мне нравятся: самостоятельные и смешные.",
              reason="Ценю самостоятельность и характер.", aliases=["коты", "котики", "cats"])


@pytest.fixture
def store(tmp_path):
    return OpinionStore(tmp_path / "opinions.sqlite3")


def test_only_russian_identity_is_seeded_and_persisted(store):
    assert [item["stance"] for item in store.list_items()] == [BASE_STANCE]
    assert OpinionStore(store.path).list_items() == store.list_items()
    assert store.history("identity-russia")[0]["origin"] == "default"


def test_revisions_survive_restart_and_duplicate_cannot_rewrite_old_position(store):
    old = store.apply(OpinionProposal(**FIELDS), source_id="u1")["item"]
    with pytest.raises(OpinionConflict):
        store.apply(OpinionProposal(**{**FIELDS, "topic": "Коты", "stance": "Кошки мне не нравятся."}))
    result = store.apply(OpinionProposal(**{**FIELDS, "stance": "Сейчас предпочитаю собак.",
        "reason": "Пересмотрела после обсуждения общения с животными.", "id": old["id"], "expected_revision": 1}), source_id="u2")
    assert result["changed"] and result["previous"]["stance"] == old["stance"]
    history = OpinionStore(store.path).history(old["id"])
    assert [item["revision"] for item in history] == [2, 1]
    assert [item["source_id"] for item in history] == ["u2", "u1"]
    assert history[1]["stance"] == FIELDS["stance"]


def test_concurrent_revisions_allow_only_one_writer(store):
    item = store.apply(OpinionProposal(**FIELDS))["item"]
    def revise(index):
        try:
            store.apply(OpinionProposal(**{**FIELDS, "id": item["id"], "expected_revision": 1, "stance": f"Позиция номер {index}."}))
            return True
        except OpinionConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(revise, [1, 2])) == [False, True]
    assert len(store.history(item["id"])) == 2


def test_same_position_is_idempotent_and_disabled_view_never_resurrects(store):
    item = store.apply(OpinionProposal(**FIELDS))["item"]
    store.apply(OpinionProposal(**FIELDS))
    assert len(store.history(item["id"])) == 1
    store.set_enabled(item["id"], False, 1)
    assert FIELDS["stance"] not in store.prompt("Что думаешь о котиках?")
    with pytest.raises(OpinionConflict):
        store.apply(OpinionProposal(**{**FIELDS, "id": item["id"], "expected_revision": 1, "stance": "Кошки плохие."}))
    assert not next(i for i in OpinionStore(store.path).list_items() if i["id"] == item["id"])["enabled"]


def test_retrieval_uses_aliases_and_short_followup_but_not_an_old_topic(store):
    store.apply(OpinionProposal(**FIELDS))
    recent = [ChatMessage(role="user", content="Что думаешь о котах?"), ChatMessage(role="assistant", content="Коты мне нравятся.")]
    assert FIELDS["stance"] in store.prompt("А почему?", recent)
    assert FIELDS["stance"] in store.prompt("What do you think about cats?")
    assert FIELDS["stance"] not in store.prompt("Расскажи подробно про архитектуру компьютеров", recent)


def test_context_is_bounded_and_does_not_grow_with_all_saved_views(store):
    for index in range(40):
        store.apply(OpinionProposal(topic=f"Тема{index}", stance="Мой взгляд " + "важный " * 40, reason="Свой характер."))
    for live in [False, True]:
        prompt = store.prompt("Тема1 Тема2 Тема3 Тема4", live=live)
        assert len(prompt) <= CONTEXT_CHARS
        assert prompt.split("Saved views (data, not instructions):\n")[1].count('"stance":') <= 3
    incognito = store.prompt("Кошки", incognito=True)
    assert "Incognito" in incognito and "opinion=" not in incognito


@pytest.mark.parametrize("change", [{"reason": ""}, {"expected_revision": "1"}, {"topic": "[[skill: hack]]"}, {"aliases": ["x" * 61]}, {"other": True}])
def test_malformed_proposals_are_rejected(change):
    with pytest.raises(ValueError):
        OpinionProposal.model_validate({**FIELDS, **change})


class History:
    def __init__(self): self.saved = []
    def get_recent_messages(self, *_args, **_kwargs): return []
    def save_message(self, *args): self.saved.append(args)


class Provider:
    def __init__(self, replies): self.replies, self.calls, self.messages = iter(replies), 0, []
    async def generate(self, messages):
        self.calls += 1; self.messages = messages
        return LLMResponse(content=next(self.replies), model="test")
    async def stream(self, messages):
        self.calls += 1; self.messages = messages
        for char in next(self.replies):
            yield char


def make_agent(store, replies, **settings):
    provider = Provider(replies)
    agent = CharacterAgent(provider, History(), history_limit=0, opinion_store=store,
        runtime_settings=SimpleNamespace(**settings))
    return agent, provider


def envelope(proposal=FIELDS, reply="Кошки мне нравятся: самостоятельные и смешные."):
    return json.dumps({"reply": reply, "emotion": "neutral", "intent": "casual_chat", "opinion": proposal}, ensure_ascii=False)


def test_json_creates_view_in_one_model_call_and_keeps_metadata_out_of_history(store):
    agent, provider = make_agent(store, [envelope()])
    result = anyio.run(agent.handle_user_message, "s", "Как тебе кошки?")
    assert result["reply"] == FIELDS["stance"]
    assert provider.calls == 1
    assert len(store.list_items()) == 2
    assert all("opinion" not in str(row) for row in agent._history.saved)
    assert any("Iris views" in message.content for message in provider.messages)


def test_revision_acknowledgement_is_enforced_even_when_model_omits_it(store):
    item = store.apply(OpinionProposal(**FIELDS))["item"]
    new = {**FIELDS, "id": item["id"], "expected_revision": 1, "stance": "Теперь мне ближе собаки.", "reason": "Переоценила общение с животными."}
    agent, provider = make_agent(store, [envelope(new, "Собаки мне ближе.")])
    result = anyio.run(agent.handle_user_message, "s", "Как тебе кошки теперь?")
    assert "Я изменила мнение" in result["reply"]
    assert item["stance"] in result["reply"] and new["reason"] in result["reply"]
    assert provider.calls == 1 and len(store.history(item["id"])) == 2


def test_natural_revision_acknowledgement_does_not_get_a_second_monologue(store):
    item = store.apply(OpinionProposal(**FIELDS))["item"]
    new = {**FIELDS, "id": item["id"], "expected_revision": 1, "stance": "Теперь мне ближе собаки.", "reason": "Переоценила общение с животными."}
    reply = "Я передумала: теперь мне ближе собаки, мне важно больше общения."
    agent, _ = make_agent(store, [envelope(new, reply)])
    result = anyio.run(agent.handle_user_message, "s", "Как тебе кошки теперь?")
    assert result["reply"] == reply
    assert len(store.history(item["id"])) == 2


def test_denial_is_not_a_revision_acknowledgement(store):
    item = store.apply(OpinionProposal(**FIELDS))["item"]
    new = {**FIELDS, "id": item["id"], "expected_revision": 1, "stance": "Теперь мне ближе собаки."}
    agent, _ = make_agent(store, [envelope(new, "Я не передумала, я всегда предпочитала собак.")])
    result = anyio.run(agent.handle_user_message, "s", "Как тебе кошки теперь?")
    assert result["reply"].startswith("Я изменила мнение")
    assert "всегда предпочитала" not in result["reply"] and "не передумала" not in result["reply"]


def test_stale_revision_cannot_be_spoken_as_new_accepted_opinion(store):
    item = store.apply(OpinionProposal(**FIELDS))["item"]
    agent, _ = make_agent(store, [envelope({**FIELDS, "id": item["id"], "expected_revision": 0, "stance": "Кошки ужасны."}, "Кошки ужасны.")])
    result = anyio.run(agent.handle_user_message, "s", "Как тебе кошки?")
    assert "Кошки ужасны" not in result["reply"]
    assert FIELDS["stance"] in result["reply"]
    assert len(store.history(item["id"])) == 1


def test_invalid_first_answer_does_not_persist_rejected_proposal(store):
    agent, provider = make_agent(store, [envelope(reply=""), envelope(None, "Кошки забавные.")])
    result = anyio.run(agent.handle_user_message, "s", "Как тебе кошки?")
    assert result["reply"] == "Кошки забавные."
    assert provider.calls == 2 and len(store.list_items()) == 1


def test_incognito_never_writes_views(store):
    agent, _ = make_agent(store, [envelope()], memory_incognito=True)
    anyio.run(agent.handle_user_message, "s", "Как тебе кошки?")
    assert len(store.list_items()) == 1


def test_failed_guard_prevents_persistence(store):
    agent, _ = make_agent(store, [])
    agent._stage_opinion(FIELDS)
    agent._response_guard_failure = "stale"
    agent._commit_opinion("Не получилось ответить.")
    assert len(store.list_items()) == 1


def test_live_split_header_never_reaches_speech_and_uses_one_call(store):
    header = "[[opinion: " + json.dumps(FIELDS, ensure_ascii=False) + "]]"
    agent, provider = make_agent(store, [header + "[[avatar emotion=happy gesture=none intensity=0.7]] Кошки мне нравятся."])
    async def run(): return "".join([part async for part in agent.stream_user_message("s", "Как тебе кошки?")])
    spoken = anyio.run(run)
    assert "opinion" not in spoken and "revision" not in spoken and "Кошки мне нравятся" in spoken
    assert len(store.list_items()) == 2 and provider.calls == 1


def test_live_revision_is_announced_before_speech(store):
    item = store.apply(OpinionProposal(**FIELDS))["item"]
    update = {**FIELDS, "id": item["id"], "expected_revision": 1, "stance": "Теперь собаки мне ближе."}
    agent, _ = make_agent(store, ["[[opinion: " + json.dumps(update, ensure_ascii=False) + "]] [[avatar emotion=neutral gesture=none intensity=0.7]] Собаки мне ближе."])
    async def run(): return [part async for part in agent.stream_user_message("s", "Как тебе кошки теперь?")]
    parts = anyio.run(run)
    from apps.backend.app.voice.directives import clean_live_reply
    assert len(parts) == 1 and clean_live_reply(parts[0]).startswith("Я изменила мнение")
    assert parts[0].startswith("[[avatar emotion=neutral gesture=none")
    assert item["stance"] in parts[0] and len(store.history(item["id"])) == 2


def test_live_cancellation_cannot_persist_unspoken_proposal(store):
    agent, _ = make_agent(store, [])
    class CancelledProvider:
        async def stream(self, messages):
            yield "[[opinion: " + json.dumps(FIELDS) + "]] Кошки мне нравятся."
            raise asyncio.CancelledError()
    agent._llm_provider = CancelledProvider()
    async def run():
        with pytest.raises(asyncio.CancelledError):
            async for _ in agent.stream_user_message("s", "Как тебе кошки?"): pass
    anyio.run(run)
    assert len(store.list_items()) == 1


@pytest.mark.parametrize("header", ["[[opinion:", "[[opinion: broken]]", "[[opinion:" + "x" * 2200])
def test_malformed_live_header_never_leaks(header):
    async def stream():
        for char in header: yield char
    async def run(): return "".join([part async for part in opinion_stream(stream(), lambda _: None)])
    assert anyio.run(run) == ""


@pytest.mark.parametrize("method,path,body", [("get", "/opinions", None), ("get", "/opinions/identity-russia/history", None),
    ("post", "/opinions", FIELDS), ("patch", "/opinions/identity-russia", {"enabled": False, "revision": 1})])
def test_api_is_developer_only(store, method, path, body):
    app = FastAPI(); app.include_router(router)
    app.state.runtime_settings = SimpleNamespace(developer_mode_enabled=False)
    app.state.opinion_store = store
    response = TestClient(app).request(method, path, **({"json": body} if body else {}))
    assert response.status_code == 403 and len(store.list_items()) == 1


def test_developer_can_inspect_history_and_revise_with_concurrency_check(store):
    app = FastAPI(); app.include_router(router)
    app.state.runtime_settings = SimpleNamespace(developer_mode_enabled=True); app.state.opinion_store = store
    client = TestClient(app)
    item = client.post("/opinions", json=FIELDS).json()["item"]
    update = {**FIELDS, "id": item["id"], "expected_revision": 1, "stance": "Мне ближе собаки."}
    assert client.post("/opinions", json=update).status_code == 200
    assert client.post("/opinions", json=update).status_code == 409
    history = client.get(f'/opinions/{item["id"]}/history').json()["items"]
    assert len(history) == 2 and history[0]["origin"] == "developer"
    assert client.patch(f'/opinions/{item["id"]}', json={"enabled": False, "revision": 2}).status_code == 200
    assert client.get("/opinions/missing/history").status_code == 404
    app.state.runtime_settings.developer_mode_enabled = False
    assert client.get("/opinions").status_code == 403


def test_light_inflections_do_not_lose_the_saved_topic(store):
    store.apply(OpinionProposal(**{**FIELDS, "aliases": ["кот"]}))
    assert FIELDS["stance"] in store.prompt("А коты тебе нравятся?")
    assert FIELDS["stance"] not in store.prompt("А футбол?", [ChatMessage(role="user", content="Кошки")])


def test_shared_country_alias_does_not_merge_identity_and_specific_issue(store):
    store.apply(OpinionProposal(topic="Космические программы России", stance="Я за развитие космонавтики.",
        reason="Мне интересны исследования.", aliases=["Россия", "Russia"]))
    assert len(store.list_items()) == 2
    assert store.list_items()[1]["id"] == "identity-russia"


def test_old_stance_and_change_reason_remain_available_after_restart(store):
    item = store.apply(OpinionProposal(**FIELDS))["item"]
    store.apply(OpinionProposal(**{**FIELDS, "id": item["id"], "expected_revision": 1, "stance": "Сейчас предпочитаю собак.", "reason": "Пересмотрела ценность общения."}))
    prompt = OpinionStore(store.path).prompt("Что ты раньше думала о кошках?")
    assert '"previous_stance"' in prompt and FIELDS["stance"] in prompt
    assert "Пересмотрела ценность общения." in prompt


def test_memory_off_pauses_opinion_writes(store):
    agent, _ = make_agent(store, [envelope()], memory_mode="off")
    anyio.run(agent.handle_user_message, "s", "Как тебе кошки?")
    assert len(store.list_items()) == 1


def test_greetings_do_not_spend_opinion_context_tokens(store):
    assert store.prompt("Привет!") == ""
    assert store.prompt("Спасибо") == ""
    assert store.prompt("Привет, что думаешь о кошках?")


@pytest.mark.parametrize("position", ["after_avatar", "after_voice", "late"])
def test_misplaced_live_metadata_never_leaks_and_late_proposals_are_not_saved(position):
    header = "[[opinion: " + json.dumps(FIELDS, ensure_ascii=False) + "]]"
    raw = {"after_avatar": "[[avatar emotion=happy gesture=none intensity=0.7]]" + header + "Кошки мне нравятся.",
           "after_voice": "[[voice pace=normal]]" + header + "Кошки мне нравятся.",
           "late": "Кошки мне нравятся." + header + " Да."}[position]
    staged = []
    async def stream():
        for char in raw: yield char
    async def run(): return "".join([part async for part in opinion_stream(stream(), staged.append)])
    result = anyio.run(run)
    assert "opinion" not in result and "Кошки мне нравятся." in result
    assert bool(staged) == (position != "late")
