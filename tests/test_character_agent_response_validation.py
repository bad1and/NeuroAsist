import logging

import anyio
import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.prompts import character_json_prompt
from apps.backend.app.context.manager import BuiltContext
from apps.backend.app.llm.base import ChatMessage, LLMResponse


@pytest.fixture
def agent() -> CharacterAgent:
    return CharacterAgent(llm_provider=None, history=None, history_limit=0)


def test_parse_response_accepts_valid_json(agent: CharacterAgent) -> None:
    result = agent._parse_response(
        '{"reply":"Привет","emotion":"happy","intent":"casual_chat"}'
    )

    assert result == {
        "reply": "Привет",
        "emotion": "happy",
        "intent": "casual_chat",
    }


def test_parse_response_accepts_json_markdown_fence(agent: CharacterAgent) -> None:
    result = agent._parse_response(
        '```json\n{"reply":"Привет","emotion":"happy","intent":"casual_chat"}\n```'
    )

    assert result == {
        "reply": "Привет",
        "emotion": "happy",
        "intent": "casual_chat",
    }


def test_parse_response_accepts_json_with_extra_text(agent: CharacterAgent) -> None:
    result = agent._parse_response(
        'Ответ:\n{"reply":"Привет","emotion":"happy","intent":"casual_chat"}'
    )

    assert result == {
        "reply": "Привет",
        "emotion": "happy",
        "intent": "casual_chat",
    }


@pytest.mark.parametrize(
    ("raw_content", "expected_reply"),
    [
        ("Привет, я не JSON", "Привет, я не JSON"),
        ('{"reply":"","emotion":"happy","intent":"casual_chat"}', "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз."),
        ('{"reply":"Привет","emotion":"banana","intent":"casual_chat"}', "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз."),
        ('{"reply":"Привет","emotion":"happy","intent":"dance"}', "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз."),
    ],
)
def test_parse_response_uses_fallback_for_invalid_llm_response(
    agent: CharacterAgent,
    raw_content: str,
    expected_reply: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        result = agent._parse_response(raw_content)

    assert result == {
        "reply": expected_reply,
        "emotion": "neutral",
        "intent": "unknown",
    }
    assert "Invalid LLM JSON response, using fallback" in caplog.text
    assert "raw_length=" in caplog.text
    assert raw_content not in caplog.text


def test_parse_response_does_not_expose_invalid_json_as_reply(agent: CharacterAgent) -> None:
    result = agent._parse_response('{"reply":"оборванный ответ')

    assert result == {
        "reply": "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз.",
        "emotion": "neutral",
        "intent": "unknown",
    }


def test_parse_response_unwraps_json_accidentally_put_in_reply(agent: CharacterAgent) -> None:
    result = agent._parse_response(
        '{"reply":"{\\\"reply\\\": \\\"Привет\\\"}","emotion":"happy","intent":"casual_chat"}'
    )

    assert result["reply"] == "Привет"


@pytest.mark.parametrize("reply", [
    "Ну? Я здесь. Опять зовёшь или есть что сказать?",
    "Ты снова начал разговор заново.",
    "Я уже говорила об этом.",
])
def test_continuity_guard_rejects_unconfirmed_accusations(agent: CharacterAgent, reply: str) -> None:
    assert agent._has_unconfirmed_continuity_accusation(reply) is True


class SequencedLLMProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0
        self.messages = []

    async def generate(self, messages):
        self.messages = messages
        content = self.responses[self.calls]
        self.calls += 1
        return LLMResponse(content=content, model="test-model")


class InMemoryHistory:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str]] = []

    def get_recent_messages(self, session_id: str, limit: int):
        return []

    def save_message(self, session_id: str, role: str, content: str) -> None:
        self.saved.append((session_id, role, content))


def test_burst_prompt_retries_when_reply_ignores_second_developer_name() -> None:
    burst = "ну вот будешь\nзнать\nвторого разработчика зовут олег"

    class BurstContext:
        def build(self, *_args, **_kwargs):
            return BuiltContext(
                [], 0,
                {
                    "pending_direct_message_count": 0,
                    "pending_user_message_count": 3,
                    "burst_compacted": True,
                },
                burst,
                ("first", "second", "current"),
            )

    provider = SequencedLLMProvider([
        '{"reply":"Теперь знаю, кто мой создатель.","emotion":"happy","intent":"casual_chat"}',
        '{"reply":"Запомнила: второго разработчика зовут Олег.","emotion":"happy","intent":"casual_chat"}',
    ])
    agent = CharacterAgent(
        provider, InMemoryHistory(), history_limit=0, context_manager=BurstContext(),
    )

    result = anyio.run(
        agent.handle_user_message, "s1", "второго разработчика зовут олег",
    )

    assert provider.calls == 2
    assert "Олег" in result["reply"]
    assert any(message.role == "user" and message.content == burst for message in provider.messages)
    assert any(
        message.role == "system" and "смысловые якоря: олег" in message.content
        for message in provider.messages
    )


def test_handle_user_message_retries_invalid_json_once() -> None:
    provider = SequencedLLMProvider(
        [
            "Привет, я не JSON",
            '{"reply":"Исправлено","emotion":"happy","intent":"casual_chat"}',
        ]
    )
    history = InMemoryHistory()
    agent = CharacterAgent(provider, history, history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "Привет")

    assert provider.calls == 2
    assert result == {
        "reply": "Исправлено",
        "emotion": "happy",
        "intent": "casual_chat",
    }
    assert history.saved == [
        ("s1", "user", "Привет"),
        ("s1", "assistant", "Исправлено"),
    ]


def test_invalid_json_repair_does_not_trigger_a_third_full_context_call() -> None:
    provider = SequencedLLMProvider(
        [
            "Привет, я не JSON",
            '{"reply":"Я норм. У тебя как? Босс опять бесит?","emotion":"smirk","intent":"casual_chat"}',
        ]
    )
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "ирис че как")

    assert provider.calls == 2
    assert result["reply"] == "У меня всё нормально, я здесь и слушаю. А у тебя как дела?"


def test_handle_user_message_does_not_warn_when_repair_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = SequencedLLMProvider(
        ["невалидный ответ", '{"reply":"Исправлено","emotion":"happy","intent":"casual_chat"}']
    )
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0)

    with caplog.at_level(logging.WARNING):
        result = anyio.run(agent.handle_user_message, "s1", "Привет")

    assert result["reply"] == "Исправлено"
    assert "Invalid LLM JSON response" not in caplog.text


def test_handle_user_message_uses_json_persona_prompt() -> None:
    provider = SequencedLLMProvider(
        ['{"reply":"Окей","emotion":"smirk","intent":"casual_chat"}']
    )
    history = InMemoryHistory()
    agent = CharacterAgent(provider, history, history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "Привет")

    assert result == {
        "reply": "Окей",
        "emotion": "smirk",
        "intent": "casual_chat",
    }
    system_prompt = provider.messages[0].content
    assert "Ты — Iris" in system_prompt
    assert "верни только один валидный JSON" in system_prompt
    assert '"reply"' in system_prompt
    assert '"emotion"' in system_prompt
    assert '"intent"' in system_prompt
    assert "Не возвращай JSON" not in system_prompt
    assert "голосовых расшифровках возможны опечатки" in system_prompt


def test_handle_user_message_keeps_dynamic_state_out_of_static_cache_prefix() -> None:
    provider = SequencedLLMProvider(
        ['{"reply":"Окей","emotion":"neutral","intent":"casual_chat"}']
    )
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0)
    marker = "DYNAMIC_STATE_MUST_NOT_ENTER_CACHE_PREFIX"

    async def invoke() -> dict:
        return await agent.handle_user_message("s1", "Привет", state_context=marker)

    anyio.run(invoke)

    assert provider.messages[0] == ChatMessage(role="system", content=character_json_prompt())
    assert marker not in provider.messages[0].content
    assert provider.messages[1].role == "system"
    assert marker in provider.messages[1].content


def test_handle_user_message_retries_unconfirmed_continuity_accusation() -> None:
    provider = SequencedLLMProvider([
        '{"reply":"Ну? Я здесь. Опять зовёшь или есть что сказать?","emotion":"annoyed","intent":"casual_chat"}',
        '{"reply":"Я здесь. Кстати, двадцать больших кружек чая — это уже перебор.","emotion":"concerned","intent":"casual_chat"}',
    ])
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "Ирис")

    assert provider.calls == 2
    assert result["reply"] == "Я здесь. Кстати, двадцать больших кружек чая — это уже перебор."


def test_status_check_retries_invented_personal_specifics() -> None:
    provider = SequencedLLMProvider([
        '{"reply":"Да всё пучком. У тебя как? Шины не пробил, босс не бесит?","emotion":"smirk","intent":"casual_chat"}',
        '{"reply":"У меня всё спокойно, сижу и слушаю. А у тебя как дела?","emotion":"neutral","intent":"casual_chat"}',
    ])
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "ирис как делишки у тебя рассказывай че как")

    assert provider.calls == 2
    assert "шины" not in result["reply"].lower()
    assert result["reply"] == "У меня всё спокойно, сижу и слушаю. А у тебя как дела?"


def test_status_check_uses_grounded_fallback_when_retry_invents_again() -> None:
    invented = '{"reply":"Я норм. У тебя как? Босс опять бесит?","emotion":"smirk","intent":"casual_chat"}'
    provider = SequencedLLMProvider([invented, invented])
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "ирис че как")

    assert provider.calls == 2
    assert result["reply"] == "У меня всё нормально, я здесь и слушаю. А у тебя как дела?"


def test_handle_user_message_retries_false_attribution_of_its_own_joke() -> None:
    previous = (
        "Идёт ёжик по лесу, видит — дом горит. Заходит, а там сидят три скелета "
        "и в карты играют."
    )

    class RecentContext:
        def build(self, *_args, **_kwargs):
            return BuiltContext(
                [ChatMessage(role="assistant", content=previous)], 0,
                {"previous_assistant_message_id": "assistant-joke", "pending_direct_message_count": 0},
            )

    provider = SequencedLLMProvider([
        '{"reply":"Сам попросил анекдот, а не бред ёжика со скелетами.","emotion":"annoyed","intent":"casual_chat"}',
        '{"reply":"Да, моя шутка с ёжиком была совсем мимо. Давай лучше другую.","emotion":"annoyed","intent":"casual_chat"}',
    ])
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0, context_manager=RecentContext())

    result = anyio.run(agent.handle_user_message, "s1", "Это вообще не анекдот, а полная бредятина")

    assert provider.calls == 2
    assert result["reply"] == "Да, моя шутка с ёжиком была совсем мимо. Давай лучше другую."


def test_assistant_content_attribution_allows_user_owned_detail(agent: CharacterAgent) -> None:
    assert agent._has_unconfirmed_assistant_content_attribution(
        "Ты сам попросил анекдот про ёжика.",
        "Ладно, вот анекдот про ёжика.",
        "Расскажи анекдот про ёжика.",
    ) is False


def test_name_only_followup_retries_a_reply_that_ignores_pending_message() -> None:
    class PendingContext:
        def build(self, *_args, **_kwargs):
            return BuiltContext([], 0, {"pending_direct_message_count": 1})

    provider = SequencedLLMProvider([
        '{"reply":"Ну? Я здесь. Опять зовёшь или есть что сказать?","emotion":"annoyed","intent":"casual_chat"}',
        '{"reply":"Двадцать больших кружек чая в день — это очень много; давай хотя бы часть заменить водой.","emotion":"concerned","intent":"casual_chat"}',
    ])
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0, context_manager=PendingContext())

    result = anyio.run(agent.handle_user_message, "s1", "Ирис")

    assert provider.calls == 2
    assert "Двадцать" in result["reply"]


def test_name_only_followup_uses_response_target_and_retries_generic_ack() -> None:
    target = "а какую ты мне модель посоветовала я не помню"

    class TargetContext:
        def build(self, *_args, **_kwargs):
            return BuiltContext(
                [],
                0,
                {"pending_direct_message_count": 1},
                target,
                ("current",),
                target,
                ("question",),
                ("модель", "посове"),
            )

    provider = SequencedLLMProvider([
        '{"reply":"Я здесь. Ты снова ищешь свою задачу или уже что-то решил?","emotion":"neutral","intent":"casual_chat"}',
        '{"reply":"Я советовала Whisper как более подходящую модель распознавания речи.","emotion":"neutral","intent":"casual_chat"}',
    ])
    agent = CharacterAgent(
        provider,
        InMemoryHistory(),
        history_limit=0,
        context_manager=TargetContext(),
    )

    result = anyio.run(agent.handle_user_message, "s1", "Ирис")

    assert provider.calls == 2
    assert "Whisper" in result["reply"]
    assert any(
        message.role == "user" and message.content == target
        for message in provider.messages
    )
    assert any(
        message.role == "system" and target in message.content
        for message in provider.messages
    )


def test_name_only_followup_uses_grounded_target_fallback_after_two_misses() -> None:
    target = "а какую ты мне модель посоветовала я не помню"

    class TargetContext:
        def build(self, *_args, **_kwargs):
            return BuiltContext(
                [],
                0,
                {"pending_direct_message_count": 1},
                target,
                ("current",),
                target,
                ("question",),
                ("модель", "посове"),
            )

    ignored = (
        '{"reply":"Я здесь. Ты снова ищешь свою задачу или уже что-то решил?",'
        '"emotion":"neutral","intent":"casual_chat"}'
    )
    provider = SequencedLLMProvider([ignored, ignored])
    agent = CharacterAgent(
        provider,
        InMemoryHistory(),
        history_limit=0,
        context_manager=TargetContext(),
    )

    result = anyio.run(agent.handle_user_message, "s1", "Ирис")

    assert provider.calls == 2
    assert "какую модель" in result["reply"]
    assert "не хочу выдумывать" in result["reply"]


def test_live_name_only_followup_is_guarded_before_stream_release() -> None:
    target = "а какую ты мне модель посоветовала я не помню"

    class TargetContext:
        def build(self, *_args, **_kwargs):
            return BuiltContext(
                [],
                0,
                {"pending_direct_message_count": 1},
                target,
                ("current",),
                target,
                ("question",),
                ("модель", "посове"),
            )

    class StreamingProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def stream(self, _messages):
            replies = [
                "Я здесь. Ты снова ищешь свою задачу или уже что-то решил?",
                "Я советовала Whisper как модель распознавания речи.",
            ]
            reply = replies[self.calls]
            self.calls += 1
            yield reply

    async def collect(agent: CharacterAgent) -> str:
        return "".join([
            chunk
            async for chunk in agent.stream_user_message("s1", "Ирис")
        ])

    provider = StreamingProvider()
    agent = CharacterAgent(
        provider,
        InMemoryHistory(),
        history_limit=0,
        context_manager=TargetContext(),
    )

    reply = anyio.run(collect, agent)

    assert provider.calls == 2
    assert reply == "Я советовала Whisper как модель распознавания речи."
    assert "снова ищешь" not in reply


def test_handle_user_message_retries_stale_previous_assistant_reply() -> None:
    previous = "Горячим — это уже другой разговор. Ты каждый раз делаешь новую заварку или доливаешь кипяток?"

    class RecentContext:
        def build(self, *_args, **_kwargs):
            return BuiltContext(
                [ChatMessage(role="assistant", content=previous)], 0,
                {"previous_assistant_message_id": "assistant-old", "pending_direct_message_count": 0},
            )

    provider = SequencedLLMProvider([
        '{"reply":"' + previous + '","emotion":"smirk","intent":"casual_chat"}',
        '{"reply":"Вот это правильно: новая заварка — без компромиссов.","emotion":"happy","intent":"casual_chat"}',
    ])
    events: list[dict] = []
    agent = CharacterAgent(
        provider, InMemoryHistory(), history_limit=0, context_manager=RecentContext(),
        event_publisher=lambda *_args: events.append(_args[-1]),
    )

    result = anyio.run(agent.handle_user_message, "s1", "каждый раз новую, естественно")

    assert provider.calls == 2
    assert result["reply"] == "Вот это правильно: новая заварка — без компромиссов."
    assert any(event["reason"] == "stale_duplicate" and event["previous_assistant_message_id"] == "assistant-old" for event in events)


def test_explicit_request_to_repeat_does_not_trigger_stale_guard() -> None:
    previous = "Горячим — это уже другой разговор. Ты каждый раз делаешь новую заварку?"

    class RecentContext:
        def build(self, *_args, **_kwargs):
            return BuiltContext([ChatMessage(role="assistant", content=previous)], 0, {})

    provider = SequencedLLMProvider([
        '{"reply":"' + previous + '","emotion":"neutral","intent":"casual_chat"}',
    ])
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0, context_manager=RecentContext())

    result = anyio.run(agent.handle_user_message, "s1", "Повтори, пожалуйста, свой прошлый вопрос")

    assert provider.calls == 1
    assert result["reply"] == previous


def test_duplicate_guard_hold_survives_being_hoisted_out_of_the_delta_loop() -> None:
    """The two-sentence hold is what lets the guard see a stale continuation.

    `duplicate_guard` is now resolved once per turn instead of on every delta.
    It still has to gate `required_sentences`, so a turn with a previous reply
    must buffer past the first sentence while a turn without one releases it
    immediately.
    """
    previous = "Заварку я бы не стала доливать кипятком, вкус уходит совсем."

    class PreviousReplyContext:
        def __init__(self, messages):
            self._messages = messages

        def build(self, *_args, **_kwargs):
            return BuiltContext(list(self._messages), 0, {})

    class SentenceStream:
        async def stream(self, _messages):
            yield "Ага, ясно. "
            yield "Тогда возьми другой сорт. "
            yield "И вода пусть остынет."

        async def generate(self, _messages):
            raise AssertionError("live path must not call generate")

    def first_chunk(context) -> str:
        agent = CharacterAgent(
            SentenceStream(), InMemoryHistory(), history_limit=0, context_manager=context,
        )

        async def collect():
            return [chunk async for chunk in agent.stream_user_message("s1", "а с чаем что")]

        return anyio.run(collect)[0]

    guarded = first_chunk(
        PreviousReplyContext([ChatMessage(role="assistant", content=previous)]),
    )
    unguarded = first_chunk(PreviousReplyContext([]))

    assert guarded == "Ага, ясно. Тогда возьми другой сорт. "
    assert unguarded == "Ага, ясно. "


def test_stale_duplicate_retry_failure_uses_safe_fallback() -> None:
    previous = "Горячим — это уже другой разговор. Ты каждый раз делаешь новую заварку или доливаешь кипяток?"

    class RecentContext:
        def build(self, *_args, **_kwargs):
            return BuiltContext([ChatMessage(role="assistant", content=previous)], 0, {})

    provider = SequencedLLMProvider([
        '{"reply":"' + previous + '","emotion":"smirk","intent":"casual_chat"}',
        '{"reply":"' + previous + '","emotion":"smirk","intent":"casual_chat"}',
    ])
    agent = CharacterAgent(provider, InMemoryHistory(), history_limit=0, context_manager=RecentContext())

    result = anyio.run(agent.handle_user_message, "s1", "каждый раз новую")

    assert provider.calls == 2
    assert "зациклилась" in result["reply"]


def test_handle_user_message_uses_deterministic_fallback_for_empty_model_response() -> None:
    provider = SequencedLLMProvider(["   ", "\n\t"])
    history = InMemoryHistory()
    agent = CharacterAgent(provider, history, history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "Да нормально")

    assert provider.calls == 2
    assert result == {
        "reply": "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз.",
        "emotion": "neutral",
        "intent": "unknown",
    }
    assert "Не смог корректно разобрать ответ модели" not in result["reply"]
    assert history.saved == [
        ("s1", "user", "Да нормально"),
        ("s1", "assistant", "Не смогла сформировать ответ. Попробуй отправить сообщение ещё раз."),
    ]


def test_handle_user_message_keeps_first_raw_text_if_retry_is_empty() -> None:
    provider = SequencedLLMProvider(["Нормальный текст без JSON", "   "])
    history = InMemoryHistory()
    agent = CharacterAgent(provider, history, history_limit=0)

    result = anyio.run(agent.handle_user_message, "s1", "Привет")

    assert provider.calls == 2
    assert result == {
        "reply": "Нормальный текст без JSON",
        "emotion": "neutral",
        "intent": "unknown",
    }
    assert history.saved == [
        ("s1", "user", "Привет"),
        ("s1", "assistant", "Нормальный текст без JSON"),
    ]
