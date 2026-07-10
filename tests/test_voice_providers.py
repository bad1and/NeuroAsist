import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.backend.app.voice.providers import EdgeTTSProvider, split_tts_chunks


def test_split_tts_chunks_keeps_short_reply_as_one_chunk() -> None:
    assert split_tts_chunks("Привет!") == ["Привет!"]


def test_split_tts_chunks_keeps_short_comma_phrases_together() -> None:
    chunks = split_tts_chunks(
        "Привет, как дела? Я хотела спросить, почему фраза обрезается после запятой?"
    )

    assert chunks == [
        "Привет, как дела?",
        "Я хотела спросить, почему фраза обрезается после запятой?",
    ]
    assert chunks[-1].endswith("?")


def test_split_tts_chunks_preserves_sentence_punctuation() -> None:
    chunks = split_tts_chunks("Да, конечно, сейчас проверю. Это может быть из-за паузы?")

    assert chunks == ["Да, конечно, сейчас проверю.", "Это может быть из-за паузы?"]
    assert chunks[0].endswith(".")
    assert chunks[1].endswith("?")


def test_split_tts_chunks_splits_regression_after_comma() -> None:
    chunks = split_tts_chunks("Привет! Отлично, а у тебя?")

    assert chunks == ["Привет!", "Отлично, а у тебя?"]


def test_split_tts_chunks_keeps_short_sentence_words_together() -> None:
    chunks = split_tts_chunks("Привет! У меня всё отлично! А у тебя?")

    assert chunks == ["Привет!", "У меня всё отлично!", "А у тебя?"]


def test_split_tts_chunks_splits_long_comma_sentence_without_tiny_fragments() -> None:
    chunks = split_tts_chunks(
        "Я сейчас проверю длинный ответ, который раньше мог обрезаться на середине, "
        "потому что Edge TTS не всегда закрывает поток вовремя, и поэтому нам нужны "
        "короткие безопасные фрагменты."
    )

    assert len(chunks) > 1
    assert " ".join(chunks) == (
        "Я сейчас проверю длинный ответ, который раньше мог обрезаться на середине, "
        "потому что Edge TTS не всегда закрывает поток вовремя, и поэтому нам нужны "
        "короткие безопасные фрагменты."
    )
    assert all(len(chunk) <= 140 for chunk in chunks)


def test_split_tts_chunks_limits_words_without_punctuation() -> None:
    text = " ".join(f"слово{i}" for i in range(1, 70))
    chunks = split_tts_chunks(text, max_chars=80, max_words=10)

    assert len(chunks) > 1
    assert " ".join(chunks) == text
    assert all(len(chunk.split()) <= 10 for chunk in chunks)
    assert all(len(chunk) <= 80 for chunk in chunks)


class _FakeStream:
    def __init__(self, messages, *, stall_after_messages: bool = False) -> None:
        self._messages = list(messages)
        self._stall_after_messages = stall_after_messages
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        if self._stall_after_messages:
            await asyncio.sleep(1)
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


class _FakeCommunicateFactory:
    def __init__(self, streams: list[_FakeStream]) -> None:
        self._streams = streams
        self.calls: list[tuple[str, str]] = []
        self.call_kwargs: list[dict] = []

    def __call__(self, text: str, voice: str, **kwargs):
        self.calls.append((text, voice))
        self.call_kwargs.append(kwargs)
        stream = self._streams.pop(0)
        return SimpleNamespace(stream=lambda: stream)


def test_edge_tts_accepts_valid_audio_when_stream_stalls_after_audio(tmp_path: Path) -> None:
    provider = EdgeTTSProvider()
    provider._STREAM_IDLE_TIMEOUT_SECONDS = 0.01
    provider._CHUNK_RETRIES = 0
    fake_edge_tts = SimpleNamespace(
        Communicate=_FakeCommunicateFactory(
            [_FakeStream([{"type": "audio", "data": b"partial"}], stall_after_messages=True)]
        )
    )
    output_path = tmp_path / "partial.mp3"

    provider._probe_duration = lambda audio_path: 1.0

    duration, voice = asyncio.run(
        provider._synthesize_chunk(fake_edge_tts, "Привет, как дела?", "voice", output_path)
    )

    assert duration == 1.0
    assert voice == "voice"
    assert output_path.read_bytes()


def test_edge_tts_rejects_empty_audio(tmp_path: Path) -> None:
    provider = EdgeTTSProvider()
    provider._CHUNK_RETRIES = 0
    fake_edge_tts = SimpleNamespace(Communicate=_FakeCommunicateFactory([_FakeStream([])]))
    output_path = tmp_path / "empty.mp3"

    with pytest.raises(RuntimeError, match="edge-tts returned no audio for chunk"):
        asyncio.run(provider._synthesize_chunk(fake_edge_tts, "Привет!", "voice", output_path))

    assert not output_path.exists()


def test_edge_tts_falls_back_to_multilingual_edge_voice(tmp_path: Path) -> None:
    provider = EdgeTTSProvider()
    provider._CHUNK_RETRIES = 0
    provider._probe_duration = lambda audio_path: None
    fake_edge_tts = SimpleNamespace(
        Communicate=_FakeCommunicateFactory(
            [
                _FakeStream([]),
                _FakeStream([{"type": "audio", "data": b"fallback-audio"}]),
            ]
        )
    )
    output_path = tmp_path / "fallback.mp3"

    duration, voice = asyncio.run(
        provider._synthesize_chunk(
            fake_edge_tts,
            "Привет!",
            "ru-RU-SvetlanaNeural",
            output_path,
        )
    )

    assert duration is None
    assert voice == "en-US-EmmaMultilingualNeural"
    assert output_path.read_bytes() == b"fallback-audio"


def test_edge_tts_accepts_non_empty_audio_when_ffprobe_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = EdgeTTSProvider()
    output_path = tmp_path / "without-ffprobe.mp3"
    output_path.write_bytes(b"fake mp3 bytes")
    monkeypatch.setattr("apps.backend.app.voice.providers.shutil.which", lambda name: None)

    duration = provider._validate_chunk_audio_path(
        output_path,
        "Да.",
        "edge-tts returned invalid audio for chunk",
    )

    assert duration is None


def test_edge_tts_rejects_audio_that_is_too_short_for_text(tmp_path: Path) -> None:
    provider = EdgeTTSProvider()
    output_path = tmp_path / "short.mp3"
    output_path.write_bytes(b"fake mp3 bytes")
    provider._probe_duration = lambda audio_path: 0.2

    with pytest.raises(RuntimeError, match="shorter than expected"):
        provider._validate_chunk_audio_path(
            output_path,
            "Это длинная фраза, которая не должна звучать меньше секунды.",
            "edge-tts returned invalid audio for chunk",
        )


def test_edge_tts_strips_trailing_comma_before_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = EdgeTTSProvider()
    streams = [
        _FakeStream([{"type": "audio", "data": b"chunk-a"}]),
    ]
    communicate_factory = _FakeCommunicateFactory(streams)
    fake_edge_tts = SimpleNamespace(Communicate=communicate_factory)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)
    monkeypatch.setattr("apps.backend.app.voice.providers.shutil.which", lambda name: "ffmpeg")
    provider._probe_duration = lambda audio_path: 2.0 if ".tmp" in audio_path.name else 1.0
    provider._concat_mp3_chunks = lambda chunk_paths, output_path: output_path.write_bytes(b"ok")

    asyncio.run(
        provider.synthesize(
            "У меня всё хорошо, спасибо!",
            "voice",
            tmp_path / "reply.mp3",
        )
    )

    assert communicate_factory.calls == [
        ("У меня всё хорошо, спасибо!", "voice"),
    ]
    assert communicate_factory.call_kwargs == [{"rate": "+20%"}]


def test_edge_tts_synthesize_cleans_temp_files_when_final_audio_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = EdgeTTSProvider()
    provider._MAX_CHUNK_CHARS = 28
    provider._MAX_CHUNK_WORDS = 5
    streams = [
        _FakeStream([{"type": "audio", "data": f"chunk-{index}".encode()}])
        for index in range(10)
    ]
    fake_edge_tts = SimpleNamespace(Communicate=_FakeCommunicateFactory(streams))
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)

    def fake_concat(chunk_paths: list[Path], output_path: Path) -> None:
        output_path.write_bytes(b"not a valid final mp3")

    def fake_probe(audio_path: Path) -> float:
        return 0.0 if ".tmp" in audio_path.name else 1.0

    provider._concat_mp3_chunks = fake_concat
    provider._probe_duration = fake_probe
    output_path = tmp_path / "reply.mp3"

    with pytest.raises(RuntimeError, match="edge-tts returned invalid audio"):
        asyncio.run(
            provider.synthesize(
                "Один два три четыре пять шесть. Семь восемь девять десять одиннадцать.",
                "voice",
                output_path,
            )
        )

    assert not output_path.exists()
    assert list(tmp_path.glob("reply.part*.mp3")) == []
    assert list(tmp_path.glob("reply.tmp.mp3")) == []
