import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import ChatMessage, LLMProvider, LLMResponse
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory
from apps.backend.app.voice.text import TextChunker, TextNormalizer
from apps.backend.app.voice.live import VoiceSessionManager
from apps.backend.app.voice.live import UtteranceContext
from apps.backend.app.voice.providers import (
    AudioChunk, EdgeTTSProvider, TTSRequest, _IncompleteEdgeStreamError,
)
from apps.backend.main import app
from apps.backend.app.api.routes import voice as voice_route
from apps.backend.app.voice.service import VoiceService


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


def test_short_sentences_are_emitted_individually_for_edge() -> None:
    chunker = TextChunker(first_target=30, max_chars=90)
    assert chunker.feed("Да. ") == ["Да."]
    assert chunker.feed("Всё хорошо. ") == ["Всё хорошо."]
    assert chunker.feed("Продолжаем разговор. ") == ["Продолжаем разговор."]


def test_tiny_complete_sentence_is_released_on_idle() -> None:
    chunker = TextChunker(first_target=50)
    assert chunker.feed("Да. ") == ["Да."]
    assert chunker.flush_idle() == []


def test_live_chunker_does_not_merge_multiple_sentences_for_edge() -> None:
    text = "Привет. Нормально, всё как обычно — копчусь потихоньку. А у тебя как?"
    chunker = TextChunker(first_target=50, next_target=80, max_chars=90, max_words=18)
    chunks = chunker.feed(TextNormalizer().normalize(text))
    chunks.extend(chunker.flush())
    assert chunks == [
        "Привет.",
        "Нормально, всё как обычно — копчусь потихоньку.",
        "А у тебя как?",
    ]


def test_live_tts_safe_jobs_smooth_soft_punctuation() -> None:
    manager = VoiceSessionManager(EdgeTTSProvider(), safe_segment_words=2)
    assert manager._split_tts_jobs(
        "Привет, да всё норм, потихоньку."
    ) == [
        "Привет да",
        "всё норм",
        "потихоньку.",
    ]
    assert manager._split_tts_jobs("Ты как?") == ["Ты как?"]
    assert manager._split_tts_jobs("Давно не виделись") == ["Давно не", "виделись"]


@pytest.mark.anyio
async def test_edge_live_stream_waits_for_delayed_audio_and_eof(monkeypatch) -> None:
    class DelayedStream:
        def __init__(self):
            self.index = 0

        async def __anext__(self):
            self.index += 1
            if self.index == 1:
                return {"type": "audio", "data": b"first"}
            if self.index == 2:
                await __import__("asyncio").sleep(0.25)
                return {"type": "audio", "data": b"second"}
            raise StopAsyncIteration

        async def aclose(self):
            return None

    stream = DelayedStream()
    factory = lambda *args, **kwargs: type("Communicate", (), {"stream": lambda self: stream})()
    monkeypatch.setitem(__import__("sys").modules, "edge_tts", type("Edge", (), {"Communicate": factory}))
    provider = EdgeTTSProvider()
    provider._POST_AUDIO_IDLE_TIMEOUT_SECONDS = 0.5
    chunks = [
        chunk.data async for chunk in provider.stream(TTSRequest("Длинная фраза", "ru", "voice"))
        if chunk.data
    ]
    assert b"".join(chunks) == b"firstsecond"


@pytest.mark.anyio
async def test_edge_live_stream_rejects_prefix_without_eof(monkeypatch) -> None:
    class StalledStream:
        def __init__(self):
            self.sent = False

        async def __anext__(self):
            if not self.sent:
                self.sent = True
                return {"type": "audio", "data": b"partial"}
            await __import__("asyncio").sleep(1)

        async def aclose(self):
            return None

    stream = StalledStream()
    factory = lambda *args, **kwargs: type("Communicate", (), {"stream": lambda self: stream})()
    monkeypatch.setitem(__import__("sys").modules, "edge_tts", type("Edge", (), {"Communicate": factory}))
    provider = EdgeTTSProvider()
    provider._POST_AUDIO_IDLE_TIMEOUT_SECONDS = 0.01
    with pytest.raises(RuntimeError, match="without EOF"):
        _ = [chunk async for chunk in provider.stream(TTSRequest("Длинная фраза", "ru", "voice"))]


@pytest.mark.anyio
async def test_adaptive_split_retries_only_unsent_text(monkeypatch) -> None:
    class AdaptiveProvider:
        def __init__(self):
            self.calls: list[str] = []

        async def stream(self, request):
            self.calls.append(request.text)
            if len(request.text.split()) > 2:
                raise RuntimeError("incomplete")
            yield AudioChunk(b"valid", "mp3", 0, is_final=True)

    provider = AdaptiveProvider()
    manager = VoiceSessionManager(provider, retry_count=1)
    monkeypatch.setattr(manager, "_validate_audio", lambda *args: 1.0)
    parts = await manager._synthesize_parts("один два три четыре", "ru", "voice")
    assert [part[0] for part in parts] == ["один два", "три четыре"]
    assert provider.calls == [
        "один два три четыре", "один два три четыре", "один два", "три четыре"
    ]


@pytest.mark.anyio
async def test_tts_worker_synthesizes_concurrently_but_sends_in_order(monkeypatch) -> None:
    class DelayedProvider:
        async def stream(self, request):
            await asyncio.sleep(0.08 if request.text == "slow" else 0.01)
            yield AudioChunk(request.text.encode(), "mp3", 0, is_final=True)

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
    started = time.perf_counter()
    await manager._tts_worker(UtteranceContext("s", "u"), queue, "ru", "voice")
    elapsed = time.perf_counter() - started
    assert elapsed < 0.14
    assert [audio.decode() for _, audio, _ in connection.segments] == ["slow", "fast"]
    assert [started["segment_id"] for started, _, _ in connection.segments] == [0, 1]


@pytest.mark.anyio
async def test_safe_segment_words_presplits_before_provider(monkeypatch) -> None:
    class RecordingProvider:
        def __init__(self):
            self.calls: list[str] = []

        async def stream(self, request):
            self.calls.append(request.text)
            yield AudioChunk(request.text.encode(), "mp3", 0, is_final=True)

    provider = RecordingProvider()
    manager = VoiceSessionManager(provider, safe_segment_words=2)
    monkeypatch.setattr(manager, "_validate_audio", lambda *args: 1.0)
    parts = await manager._synthesize_parts("один два три четыре", "ru", "voice")
    assert [part[0] for part in parts] == ["один два", "три четыре"]
    assert sorted(provider.calls) == ["один два", "три четыре"]


@pytest.mark.anyio
async def test_validated_tiny_prefix_may_complete_adaptive_recovery(monkeypatch) -> None:
    class TinyPrefixProvider:
        async def stream(self, request):
            yield AudioChunk(b"complete-tiny-audio", "mp3", 0)
            raise _IncompleteEdgeStreamError("missing EOF")

    manager = VoiceSessionManager(TinyPrefixProvider(), retry_count=1)
    monkeypatch.setattr(manager, "_validate_audio", lambda *args: 0.8)
    parts = await manager._synthesize_parts("два слова", "ru", "voice")
    assert [(part[0], part[1]) for part in parts] == [
        ("два слова", b"complete-tiny-audio")
    ]


@pytest.mark.anyio
async def test_validated_non_tiny_audio_without_eof_is_split(monkeypatch) -> None:
    class CompleteNoEofProvider:
        def __init__(self):
            self.calls: list[str] = []

        async def stream(self, request):
            self.calls.append(request.text)
            yield AudioChunk(b"complete-audio", "mp3", 0)
            raise _IncompleteEdgeStreamError("missing EOF")

    provider = CompleteNoEofProvider()
    manager = VoiceSessionManager(provider, retry_count=1)

    def validate(audio, audio_format, text, enforce_min_duration=True):
        assert enforce_min_duration is False
        return 2.0

    monkeypatch.setattr(manager, "_validate_audio", validate)
    parts = await manager._synthesize_parts("один два три четыре", "ru", "voice")
    assert [part[0] for part in parts] == ["один два", "три четыре"]
    assert provider.calls == ["один два три четыре", "один два", "три четыре"]


@pytest.mark.anyio
async def test_short_non_tiny_audio_without_eof_still_splits(monkeypatch) -> None:
    class ShortNoEofProvider:
        async def stream(self, request):
            yield AudioChunk(f"short:{request.text}".encode(), "mp3", 0)
            raise _IncompleteEdgeStreamError("missing EOF")

    manager = VoiceSessionManager(ShortNoEofProvider(), retry_count=0)

    def validate(audio, audio_format, text, enforce_min_duration=True):
        if enforce_min_duration:
            raise RuntimeError("TTS provider returned suspiciously short audio")
        return 0.4

    monkeypatch.setattr(manager, "_validate_audio", validate)
    parts = await manager._synthesize_parts("один два три четыре", "ru", "voice")
    assert [part[0] for part in parts] == ["один два", "три четыре"]


@pytest.mark.anyio
async def test_live_tiny_recovery_allows_two_long_words(monkeypatch) -> None:
    class TinyPrefixProvider:
        async def stream(self, request):
            yield AudioChunk(b"complete-tiny-audio", "mp3", 0)
            raise _IncompleteEdgeStreamError("missing EOF")

    manager = VoiceSessionManager(TinyPrefixProvider(), retry_count=0)

    def validate(audio, audio_format, text, enforce_min_duration=True):
        assert enforce_min_duration is False
        return 0.2

    monkeypatch.setattr(manager, "_validate_audio", validate)
    parts = await manager._synthesize_parts("девяностосимвольный сегмент", "ru", "voice")
    assert [(part[0], part[1]) for part in parts] == [
        ("девяностосимвольный сегмент", b"complete-tiny-audio")
    ]


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


def test_live_rest_and_websocket_stream_protocol(monkeypatch, tmp_path: Path) -> None:
    class RouteStreamingProvider(StreamingProvider):
        def __init__(self, settings, model=None):
            pass

    settings = app.state.settings
    previous_service = app.state.voice_service
    previous_manager = app.state.voice_session_manager
    previous_stt = settings.voice_stt_provider
    previous_tts = settings.voice_tts_provider
    previous_audio_dir = settings.voice_audio_dir
    settings.voice_stt_provider = "mock"
    settings.voice_tts_provider = "mock"
    settings.voice_audio_dir = str(tmp_path / "audio")
    app.state.voice_service = VoiceService(settings)
    app.state.voice_session_manager = VoiceSessionManager(app.state.voice_service.tts_provider, tts_timeout=2)
    monkeypatch.setattr(voice_route, "DeepSeekProvider", RouteStreamingProvider)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/voice/live-test?version=1") as socket:
                response = client.post(
                    "/voice/chat",
                    data={"session_id": "live-test", "language": "ru", "live": "true"},
                    files={"audio": ("voice.webm", b"test-audio", "audio/webm")},
                )
                assert response.status_code == 200
                body = response.json()
                assert body["status"] == "streaming"
                assert body["transcript"] == "Тестовое голосовое сообщение"
                events = [socket.receive_json() for _ in range(4)]
                event_types = [event["type"] for event in events]
                assert event_types[:3] == [
                    "voice.utterance.started", "voice.metadata", "voice.text.delta",
                ]
                assert event_types[3] in {"voice.text.delta", "tts.segment.started"}
                assert all(event["utterance_id"] == body["utterance_id"] for event in events)
    finally:
        app.state.voice_service.clear_audio_dir()
        app.state.voice_service = previous_service
        app.state.voice_session_manager = previous_manager
        settings.voice_stt_provider = previous_stt
        settings.voice_tts_provider = previous_tts
        settings.voice_audio_dir = previous_audio_dir
