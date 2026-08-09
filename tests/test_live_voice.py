import asyncio
import time
from pathlib import Path

import pytest

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import ChatMessage, LLMProvider, LLMResponse
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory
from apps.backend.app.voice.text import TextChunker, TextNormalizer
from apps.backend.app.voice.directives import LiveDirectiveParser, AvatarDirective, clean_live_reply, make_live_directive_expressive
from apps.backend.app.voice.live import VoiceSessionManager
from apps.backend.app.voice.live import UtteranceContext
from apps.backend.app.voice.providers import AudioChunk, MockTTSProvider
from apps.backend.app.voice.delivery import (
    LiveVoiceDirectiveParser,
    SpeechEmphasis,
    SpeechPace,
    VoiceDirective,
    clean_voice_directives,
)


class StreamingProvider(LLMProvider):
    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        return LLMResponse(content="unused", model="fake")

    async def stream(self, messages: list[ChatMessage]):
        yield "Первая фраза. "
        yield "Вторая фраза."


class FakeVoiceConnection:
    def __init__(self):
        self.segments: list[tuple[dict, bytes, dict]] = []

    async def segment(self, started, audio, finished):
        self.segments.append((started, audio, finished))


def test_normalizer_keeps_ui_independent_tts_copy() -> None:
    source = "**Ответ** `value` https://example.com\n```python\nsecret()\n```"
    assert TextNormalizer().normalize(source) == "Ответ value ссылка"
    assert "https://example.com" in source


def test_voice_directive_parser_is_fragment_safe_fail_closed_and_limited() -> None:
    parser = LiveVoiceDirectiveParser(max_directives=3)
    output = []
    for delta in (
        "Первая. [[voi",
        "ce pace=slow emphasis=light]]Вторая. ",
        "[[voice pace=unknown emphasis=wrong]]Третья. ",
        "[[voice broken]]Четвёртая. ",
        "[[voice pace=fast emphasis=light]]Пятая.",
    ):
        output.extend(parser.feed(delta))
    output.extend(parser.finish())

    visible = "".join(item for item in output if isinstance(item, str))
    directives = [item for item in output if isinstance(item, VoiceDirective)]
    assert "[[voice" not in visible
    assert visible == "Первая. Вторая. Третья. Четвёртая. Пятая."
    assert directives[0].pace is SpeechPace.SLOW
    assert directives[0].emphasis is SpeechEmphasis.LIGHT
    assert directives[1] == VoiceDirective()
    assert len(directives) == 3


def test_overlong_voice_directive_never_leaks_visible_text() -> None:
    value = "До. [[voice " + ("x" * 200) + "]] После."
    assert clean_voice_directives(value) == "До.  После."


def test_live_directive_is_fragment_safe_and_never_becomes_spoken_text() -> None:
    parser = LiveDirectiveParser()
    directive, text = parser.feed("[[avatar emotion=smirk gesture=shr")
    assert directive is None and text == []
    directive, text = parser.feed("ug intensity=0.7]]\nНу да, конечно.")
    assert directive is not None
    assert (directive.emotion, directive.gesture, directive.intensity) == ("smirk", "shrug", .7)
    assert text == ["\nНу да, конечно."]
    assert clean_live_reply("[[avatar emotion=smirk gesture=shrug intensity=0.7]]\nНу да, конечно.") == "Ну да, конечно."


def test_legacy_leading_direction_becomes_avatar_metadata_not_tts() -> None:
    parser = LiveDirectiveParser()
    directive, text = parser.feed("(саркастически ухмыляясь) Ну да, конечно.")
    assert directive is not None
    assert (directive.emotion, directive.gesture) == ("smirk", "shrug")
    assert text == ["Ну да, конечно."]
    assert clean_live_reply("(саркастически ухмыляясь) Ну да, конечно.") == "Ну да, конечно."


def test_malformed_machine_header_is_not_spoken() -> None:
    parser = LiveDirectiveParser()
    directive, text = parser.feed("[[avatar emotion=not-real gesture=shrug intensity=2]] Привет")
    assert directive is not None
    assert directive.emotion == "neutral"
    assert text == [" Привет"]


def test_live_directive_fallback_is_visible_and_contextual() -> None:
    assert make_live_directive_expressive(AvatarDirective(), "Почему опять ошибка?") == AvatarDirective("annoyed", "frustration", 1.0)
    assert make_live_directive_expressive(AvatarDirective(), "Спасибо, это круто") == AvatarDirective("happy", "talk", 1.0)
    assert make_live_directive_expressive(AvatarDirective(), "Меня это бесит") == AvatarDirective("annoyed", "frustration", 1.0)
    assert make_live_directive_expressive(AvatarDirective(), "Как это работает?") == AvatarDirective("thinking", "question", 1.0)
    assert make_live_directive_expressive(AvatarDirective(), "Сделай заметку") == AvatarDirective("neutral", "talk", 1.0)
    assert make_live_directive_expressive(AvatarDirective("thinking", "auto", .7), "Почему?") == AvatarDirective("thinking", "question", .7)


def test_chunker_protects_decimal_and_russian_abbreviation() -> None:
    chunker = TextChunker()
    assert chunker.feed("Значение 3.14, т. е. число. Дальше текст. ") == [
        "Значение 3.14, т. е. число.",
        "Дальше текст.",
    ]
    assert chunker.flush_idle() == []


def test_chunker_splits_long_text_and_flushes_tail() -> None:
    chunker = TextChunker(max_chars=40)
    chunks = chunker.feed("слово " * 20)
    chunks.extend(chunker.flush())
    assert "".join(chunks).replace(" ", "") == ("слово" * 20)
    assert all(len(chunk) <= 40 for chunk in chunks)


def test_live_chunker_enforces_character_and_word_limits() -> None:
    text = " ".join(f"слово{index}" for index in range(60))
    chunker = TextChunker(max_chars=90, max_words=18)
    chunks = chunker.feed(text)
    chunks.extend(chunker.flush())
    assert " ".join(chunks) == text
    assert all(len(chunk) <= 90 for chunk in chunks)
    assert all(len(chunk.split()) <= 18 for chunk in chunks)


def test_short_sentences_are_emitted_individually() -> None:
    chunker = TextChunker(first_target=30, max_chars=90)
    assert chunker.feed("Да. ") == ["Да."]
    assert chunker.feed("Всё хорошо. ") == ["Всё хорошо."]
    assert chunker.feed("Продолжаем разговор. ") == ["Продолжаем разговор."]


def test_tiny_complete_sentence_is_released_on_idle() -> None:
    chunker = TextChunker(first_target=50)
    assert chunker.feed("Да. ") == ["Да."]
    assert chunker.flush_idle() == []


def test_live_chunker_does_not_merge_multiple_sentences() -> None:
    text = "Привет. Нормально, всё как обычно — копчусь потихоньку. А у тебя как?"
    chunker = TextChunker(first_target=50, next_target=80, max_chars=90, max_words=18)
    chunks = chunker.feed(TextNormalizer().normalize(text))
    chunks.extend(chunker.flush())
    assert chunks == [
        "Привет.",
        "Нормально, всё как обычно — копчусь потихоньку.",
        "А у тебя как?",
    ]


def test_live_tts_safe_jobs_keep_short_sentence_whole() -> None:
    manager = VoiceSessionManager(MockTTSProvider(), safe_segment_words=10)
    assert manager._split_tts_jobs("Привет, да всё норм, потихоньку.") == [
        "Привет, да всё норм, потихоньку.",
    ]
    assert manager._split_tts_jobs("Ты как?") == ["Ты как?"]
    assert manager._split_tts_jobs("Давно не виделись") == ["Давно не виделись"]


def test_live_tts_keeps_a_full_conversational_thought_together_by_default() -> None:
    manager = VoiceSessionManager(MockTTSProvider(), safe_segment_words=18)
    thought = "Ну я сначала спокойно проверю настройки потом перезапущу приложение и скажу что получилось"

    assert len(thought.split()) == 13
    assert manager._split_tts_jobs(thought) == [thought]


def test_live_tts_jobs_split_long_text_without_tiny_tail() -> None:
    manager = VoiceSessionManager(MockTTSProvider(), safe_segment_words=10)
    text = (
        "Первый длинный фрагмент нужно произнести достаточно быстро, чтобы пользователь "
        "услышал начало ответа без задержки, а короткий хвост не должен остаться отдельно."
    )
    jobs = manager._split_tts_jobs(text)

    assert len(jobs) > 1
    assert " ".join(jobs) == text
    assert all(len(job.split()) <= 18 for job in jobs)
    assert len(jobs[-1].split()) > 3


@pytest.mark.anyio
async def test_adaptive_split_retries_unsent_text(monkeypatch) -> None:
    class AdaptiveProvider:
        def __init__(self):
            self.calls: list[str] = []

        async def stream(self, request):
            self.calls.append(request.text)
            if len(request.text.split()) > 2:
                raise RuntimeError("incomplete")
            yield AudioChunk(b"valid", "wav", 0, is_final=True)

    provider = AdaptiveProvider()
    manager = VoiceSessionManager(provider, retry_count=1)
    monkeypatch.setattr(manager, "_validate_audio", lambda *args: 1.0)
    parts = await manager._synthesize_parts("один два три четыре", "ru", "xenia")
    assert [part[0] for part in parts] == ["один два", "три четыре"]
    assert provider.calls == [
        "один два три четыре", "один два три четыре", "один два", "три четыре"
    ]


@pytest.mark.anyio
async def test_tts_worker_synthesizes_concurrently_but_sends_in_order(monkeypatch) -> None:
    class DelayedProvider:
        async def stream(self, request):
            await asyncio.sleep(0.08 if request.text == "slow" else 0.01)
            yield AudioChunk(request.text.encode(), "wav", 0, is_final=True)

    manager = VoiceSessionManager(
        DelayedProvider(),
        queue_size=4,
        tts_concurrency_mode="2",
        tts_concurrency_min=1,
        tts_concurrency_max=2,
    )
    monkeypatch.setattr(manager, "_validate_audio", lambda *args: 1.0)
    connection = FakeVoiceConnection()
    manager._connections["s"] = connection
    queue = asyncio.Queue()
    await queue.put("slow")
    await queue.put("fast")
    await queue.put(None)
    context = UtteranceContext("s", "u")
    manager._active["s"] = context
    started = time.perf_counter()
    await manager._tts_worker(context, queue, "ru", "xenia")
    elapsed = time.perf_counter() - started
    assert elapsed < 0.14
    assert [audio.decode() for _, audio, _ in connection.segments] == ["slow", "fast"]
    assert [started["segment_id"] for started, _, _ in connection.segments] == [0, 1]


@pytest.mark.anyio
async def test_stale_generation_cannot_send_late_tts_segment() -> None:
    manager = VoiceSessionManager(MockTTSProvider())
    connection = FakeVoiceConnection()
    manager._connections["s"] = connection
    stale = UtteranceContext("s", "old", generation=1)
    manager._active["s"] = UtteranceContext("s", "new", generation=2)
    with pytest.raises(asyncio.CancelledError):
        await manager._send_tts_part(
            stale,
            0,
            ("old text", b"old audio", "wav", 0.1, 1),
            queue_depth=0,
            synth_ms=1,
        )
    assert connection.segments == []


@pytest.mark.anyio
async def test_safe_segment_words_keeps_successful_sentence_whole(monkeypatch) -> None:
    class RecordingProvider:
        def __init__(self):
            self.calls: list[str] = []

        async def stream(self, request):
            self.calls.append(request.text)
            yield AudioChunk(request.text.encode(), "wav", 0, is_final=True)

    provider = RecordingProvider()
    manager = VoiceSessionManager(provider, safe_segment_words=2)
    monkeypatch.setattr(manager, "_validate_audio", lambda *args: 1.0)
    parts = await manager._synthesize_parts("один два три четыре", "ru", "xenia")
    assert [part[0] for part in parts] == ["один два три четыре"]
    assert provider.calls == ["один два три четыре"]


@pytest.mark.anyio
async def test_streaming_agent_commits_complete_history(tmp_path: Path) -> None:
    history = SQLiteMessageHistory(tmp_path / "history.sqlite3")
    history.init_db()
    agent = CharacterAgent(StreamingProvider(), history, history_limit=10)
    result = [delta async for delta in agent.stream_user_message("s", "Привет")]
    assert "".join(result) == "Первая фраза. Вторая фраза."
    saved = history.get_recent_messages("s", 10)
    assert [(item.role, item.content) for item in saved] == [
        ("user", "Привет"),
        ("assistant", "Первая фраза. Вторая фраза."),
    ]


@pytest.mark.anyio
async def test_streaming_agent_commits_history_without_avatar_directive(tmp_path: Path) -> None:
    class DirectedProvider(StreamingProvider):
        async def stream(self, messages: list[ChatMessage]):
            yield "[[avatar emotion=smirk gesture=shrug intensity=0.7]]\nНу да, конечно."

    history = SQLiteMessageHistory(tmp_path / "history.sqlite3")
    history.init_db()
    agent = CharacterAgent(DirectedProvider(), history, history_limit=10)
    raw = [delta async for delta in agent.stream_user_message("s", "Привет", stored_reply_transform=clean_live_reply)]
    assert "[[avatar" in "".join(raw)
    assert [(item.role, item.content) for item in history.get_recent_messages("s", 10)] == [
        ("user", "Привет"), ("assistant", "Ну да, конечно."),
    ]


@pytest.mark.anyio
async def test_streaming_agent_uses_character_persona_prompt(tmp_path: Path) -> None:
    class RecordingStreamingProvider(StreamingProvider):
        def __init__(self):
            self.messages: list[ChatMessage] = []

        async def stream(self, messages: list[ChatMessage]):
            self.messages = messages
            yield "Окей."

    provider = RecordingStreamingProvider()
    history = SQLiteMessageHistory(tmp_path / "history.sqlite3")
    history.init_db()
    agent = CharacterAgent(provider, history, history_limit=10)

    result = [delta async for delta in agent.stream_user_message("s", "Привет")]

    assert result == ["Окей."]
    system_prompt = provider.messages[0].content
    assert "Ты — Iris" in system_prompt
    assert "NeuroAsist" not in system_prompt
    assert "дружелюбный персонаж" not in system_prompt
    assert "не возвращай JSON" in system_prompt
    assert "верни только один валидный JSON" not in system_prompt
    assert '"reply"' not in system_prompt
    assert "[[avatar emotion=smirk gesture=shrug intensity=0.7]]" in system_prompt
    assert "Не пиши скобочные ремарки действий" in system_prompt
    assert "Не выдумывай биографии" in system_prompt
    assert "ты не про того" in system_prompt
    assert "Не упоминай тесты" in system_prompt


@pytest.mark.anyio
async def test_live_stream_retries_stale_reply_before_emitting_delta(tmp_path: Path) -> None:
    previous = "Горячим — это уже другой разговор. Ты каждый раз делаешь новую заварку или доливаешь кипяток?"

    class RecentContext:
        def build(self, *_args, **_kwargs):
            from apps.backend.app.context.manager import BuiltContext
            return BuiltContext([ChatMessage(role="assistant", content=previous)], 0, {"previous_assistant_message_id": "old"})

    class StaleThenFreshProvider(LLMProvider):
        def __init__(self):
            self.calls = 0

        async def generate(self, _messages):
            return LLMResponse(content="unused", model="test")

        async def stream(self, _messages):
            self.calls += 1
            if self.calls == 1:
                yield previous
            else:
                yield "Вот это правильно: каждый раз свежая заварка."

    provider = StaleThenFreshProvider()
    history = SQLiteMessageHistory(tmp_path / "history.sqlite3")
    history.init_db()
    agent = CharacterAgent(provider, history, history_limit=10, context_manager=RecentContext())

    result = [delta async for delta in agent.stream_user_message("s", "каждый раз новую")]

    assert provider.calls == 2
    assert "Горячим" not in "".join(result)
    assert "свежая заварка" in "".join(result)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Сделай заметку", "task_request"),
        ("Почему небо синее?", "question"),
        ("Привет!", "casual_chat"),
        ("", "unknown"),
    ],
)
def test_local_intent(text: str, expected: str) -> None:
    assert CharacterAgent.classify_intent(text) == expected


def test_live_input_uses_only_protocol_v3() -> None:
    from fastapi.testclient import TestClient

    from apps.backend.main import app

    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice-input/live-test?version=3") as socket:
            socket.send_json({
                "type": "voice.input.start",
                "protocol_version": 3,
                "sample_rate": 16000,
                "channels": 1,
                "format": "pcm_s16le",
                "language": "ru",
                "capture_profile": "live",
            })
            ready = socket.receive_json()
            assert ready["type"] == "voice.input.ready"
            assert ready["protocol_version"] == 3
            socket.send_bytes(b"\0\0" * 512)
            socket.send_json({"type": "voice.input.stop"})
