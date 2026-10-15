import json

import anyio
import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.context.manager import ContextManager
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.storage.timeline import TimelineStore, TimelineHistoryAdapter
from tests.test_character_agent_response_validation import SequencedLLMProvider


@pytest.mark.parametrize("reply", [
    "Я сказала про ёжика, но это моя неудачная шутка.",
    "Ты просил мирные новости в городе, а я начала про войну.",
    "Ты просил анекдот. Я добавила ёжика со скелетами — это моя ошибка.",
    "Ты не просил ёжика, это я его придумала.",
    "Ты просил мирные сводки, блядь. Я не так поняла.",
])
def test_owning_a_mistake_or_restating_the_topic_is_not_false_attribution(reply):
    agent = CharacterAgent(None, None, 0)
    previous = "Я рассказала про ёжика со скелетами и новости в городе. Блядь, это сводки."
    assert not agent._has_unconfirmed_assistant_content_attribution(reply, previous, "Я просил мирное, не войну")


def test_attribution_is_grounded_in_recent_user_words():
    agent = CharacterAgent(None, None, 0)
    agent._grounding_users = ("Придумай шутку про ёжика",)
    assert not agent._has_unconfirmed_assistant_content_attribution("Ты сам попросил про ёжика.", "Вот ёжик со скелетами.", "Мда")
    assert agent._has_unconfirmed_assistant_content_attribution("Сам попросил про скелетов.", "Вот ёжик со скелетами.", "Мда")


def test_complaint_about_repetition_does_not_allow_another_copy():
    assert not CharacterAgent._user_allows_repetition("Ты опять повторяешь одно и то же", "Старый ответ")
    assert CharacterAgent._user_allows_repetition("Повтори дословно", "Старый ответ")
    assert not CharacterAgent._user_allows_repetition("Не надо повторить предыдущий ответ", "Старый ответ")


def test_live_prefix_can_continue_without_a_retry():
    previous = "Сначала очередь принимает задачу и кладёт её в список ожидания."
    continuation = " Затем работник забирает следующую задачу и выполняет её по порядку."

    class Provider:
        calls = 0
        async def stream(self, _):
            self.calls += 1
            yield previous
            yield continuation

    provider = Provider()
    agent = CharacterAgent(provider, None, 0)
    async def read():
        return "".join([c async for c in agent._guarded_live_stream([], previous_assistant_reply=previous, user_text="А что дальше?")])
    assert anyio.run(read) == previous + continuation
    assert provider.calls == 1
    assert agent._response_guard_failure is None


@pytest.mark.parametrize("followup", ["Ирис", "Ответь на прошлый вопрос", "Продолжи"])
def test_failed_answer_is_visible_but_does_not_close_the_original_question(tmp_path, followup):
    store = TimelineStore(tmp_path / "history.sqlite3")
    store.init_db()
    original = "Объясни, как работает очередь задач."
    stale = "Сегодня разговор совсем о другом, я просто сижу здесь и жду следующего вопроса."
    store.append_message(role="assistant", content=stale, input_mode="text", session_id="s")
    provider = SequencedLLMProvider([
        json.dumps({"reply": stale, "emotion": "neutral", "intent": "casual_chat"}),
        json.dumps({"reply": stale, "emotion": "neutral", "intent": "casual_chat"}),
        json.dumps({"reply": "Очередь выполняет задачи по порядку, по одной за раз.", "emotion": "neutral", "intent": "question"}),
    ])
    agent = CharacterAgent(provider, TimelineHistoryAdapter(store), 8, context_manager=ContextManager(store))
    failed = anyio.run(agent.handle_user_message, "s", original)
    assert "Вопрос сохранился" in failed["reply"]
    rows = store.list_messages(20, session_id="s")[0]
    failure = next(m for m in rows if m.metadata.get("response_failed"))
    assert MemoryService.is_eligible_automatic_source(failure) is False
    assert failed["reply"] not in [m.content for m in store.get_recent_messages("s", 20)]
    result = anyio.run(agent.handle_user_message, "s", followup)
    assert result["reply"].startswith("Очередь выполняет")
    assert provider.calls == 3
    assert agent._response_guard_failure is None


@pytest.mark.parametrize("content,metadata", [
    ("Ответ не получился", {"tokens": {"response_failed": True}}),
    ("Вот же заело: я опять тащу прошлый ответ вместо нового. Давай ещё раз.", {}),
])
def test_voice_failure_metadata_and_legacy_fallback_are_recoverable(tmp_path, content, metadata):
    store = TimelineStore(tmp_path / "voice.sqlite3")
    store.init_db()
    question, _ = store.append_message(role="user", content="Объясни очередь задач", input_mode="voice")
    failure, _ = store.append_message(role="assistant", content=content, input_mode="voice", metadata=metadata)
    current, _ = store.append_message(role="user", content="Ответь на прошлый вопрос", input_mode="text")
    context = ContextManager(store).build(current.content, current_message_id=current.id)
    assert context.response_target_message_ids == (question.id,)
    assert all(content not in m.content for m in context.messages)
    assert not MemoryService.is_eligible_automatic_source(failure)


def test_changed_fact_does_not_count_as_a_stale_paraphrase():
    previous = "В очереди обработки сейчас ожидают 12 задач. Работник берёт задачи по порядку и возвращает результат после выполнения каждой задачи."
    updated = previous.replace("12", "13")
    assert CharacterAgent._stale_duplicate_assessment(updated, previous, "Сколько задач сейчас?")["stale"] is False
    assert CharacterAgent._stale_duplicate_assessment(previous, previous, "Сколько задач сейчас?")["stale"] is True
