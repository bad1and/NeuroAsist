import asyncio
import contextlib
import logging
import os
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from apps.backend.app.core.config import Settings
from apps.backend.app.voice.providers import (
    AudioChunk,
    FasterWhisperSTTProvider,
    SileroTTSProvider,
    TTSRequest,
    split_tts_chunks,
    waveform_to_wav_bytes,
)
from apps.backend.app.voice.service import VoiceService


def test_split_tts_chunks_keeps_short_reply_as_one_chunk() -> None:
    assert split_tts_chunks("Привет!") == ["Привет!"]


def test_split_tts_chunks_preserves_sentence_punctuation() -> None:
    chunks = split_tts_chunks("Да, конечно, сейчас проверю. Это может быть из-за паузы?")

    assert chunks == ["Да, конечно, сейчас проверю.", "Это может быть из-за паузы?"]
    assert chunks[0].endswith(".")
    assert chunks[1].endswith("?")


def test_split_tts_chunks_limits_words_without_punctuation() -> None:
    text = " ".join(f"слово{i}" for i in range(1, 70))
    chunks = split_tts_chunks(text, max_chars=80, max_words=10)

    assert len(chunks) > 1
    assert " ".join(chunks) == text
    assert all(len(chunk.split()) <= 10 for chunk in chunks)
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_faster_whisper_auto_retries_cpu_on_cuda_runtime_dll_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[tuple[str, str]] = []

    class FakeWhisperModel:
        def __init__(self, model_name: str, *, device: str, compute_type: str) -> None:
            calls.append((device, compute_type))
            self.device = device

        def transcribe(self, *args, **kwargs):
            if self.device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return [SimpleNamespace(text="Привет")], SimpleNamespace(language="ru")

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"fake")

    provider = FasterWhisperSTTProvider("small", "auto", "int8")
    with caplog.at_level(logging.INFO):
        result = asyncio.run(provider.transcribe(audio_path, "ru"))

    assert result.text == "Привет"
    assert provider._selected_device == "cpu"
    assert provider._selected_compute_type == "int8"
    assert calls == [("cuda", "int8_float16"), ("cpu", "int8")]
    assert "FasterWhisper CUDA runtime failed, retrying on CPU" in caplog.text
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_waveform_to_wav_bytes_clamps_and_writes_pcm16_wav() -> None:
    wav_bytes = waveform_to_wav_bytes(np.array([-2.0, -0.5, 0.0, 0.5, 2.0]), 24000)

    with wave.open(__import__("io").BytesIO(wav_bytes), "rb") as audio:
        assert audio.getframerate() == 24000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")

    assert pcm.tolist() == [-32767, -16383, 0, 16383, 32767]


class FakeSileroModel:
    speakers = ["xenia", "baya"]

    def __init__(self, delay: float = 0.0) -> None:
        self.calls: list[str] = []
        self.delay = delay
        self.to_device: str | None = None

    def to(self, device: str):
        self.to_device = device
        return self

    def apply_tts(self, *, text: str, speaker: str, sample_rate: int):
        if self.delay:
            import time

            time.sleep(self.delay)
        self.calls.append(text)
        return np.array([0.0, 0.2, -0.2, 0.0], dtype=np.float32)


class InPlaceDeviceSileroModel(FakeSileroModel):
    def to(self, device: str):
        self.to_device = device
        return None


def fake_torch(cuda_available: bool = False):
    return SimpleNamespace(
        set_num_threads=lambda value: None,
        cuda=SimpleNamespace(is_available=lambda: cuda_available),
        hub=SimpleNamespace(load=lambda **kwargs: (FakeSileroModel(), None)),
        inference_mode=contextlib.nullcontext,
    )


def install_fake_torch(monkeypatch: pytest.MonkeyPatch, *, cuda_available: bool = False) -> None:
    monkeypatch.setitem(sys.modules, "torch", fake_torch(cuda_available))


def test_silero_model_loads_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_torch(monkeypatch)
    loads = 0

    def loader():
        nonlocal loads
        loads += 1
        return FakeSileroModel()

    provider = SileroTTSProvider(model_loader=loader, warmup=False)
    asyncio.run(provider.preload())
    asyncio.run(provider.preload())

    assert loads == 1


def test_silero_configures_certifi_ca_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    import certifi

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    provider = SileroTTSProvider(model_loader=FakeSileroModel, warmup=False)

    provider._configure_certifi_ca_bundle()

    assert os.environ["SSL_CERT_FILE"] == certifi.where()


def test_parallel_silero_preload_loads_model_once(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_torch(monkeypatch)
    loads = 0

    def loader():
        nonlocal loads
        loads += 1
        return FakeSileroModel()

    async def run() -> None:
        provider = SileroTTSProvider(model_loader=loader, warmup=False)
        await asyncio.gather(provider.preload(), provider.preload(), provider.preload())

    asyncio.run(run())

    assert loads == 1


def test_silero_warmup_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_torch(monkeypatch)
    model = FakeSileroModel()
    provider = SileroTTSProvider(model_loader=lambda: model, warmup=True)

    asyncio.run(provider.preload())
    asyncio.run(provider.preload())

    assert model.calls == ["Привет."]


def test_silero_accepts_in_place_model_to(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_torch(monkeypatch)
    model = InPlaceDeviceSileroModel()
    provider = SileroTTSProvider(model_loader=lambda: model, warmup=True)

    asyncio.run(provider.preload())

    assert model.to_device == "cpu"
    assert model.calls == ["Привет."]


@pytest.mark.anyio
async def test_silero_stream_returns_single_final_wav_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_torch(monkeypatch)
    provider = SileroTTSProvider(model_loader=FakeSileroModel, warmup=False)

    chunks = [chunk async for chunk in provider.stream(TTSRequest("Привет", "ru", "ignored"))]

    assert len(chunks) == 1
    assert isinstance(chunks[0], AudioChunk)
    assert chunks[0].format == "wav"
    assert chunks[0].is_final is True
    with wave.open(__import__("io").BytesIO(chunks[0].data), "rb") as audio:
        assert audio.getframerate() == 24000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2


@pytest.mark.anyio
async def test_silero_uses_requested_valid_speaker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_fake_torch(monkeypatch)
    model = FakeSileroModel()
    provider = SileroTTSProvider(model_loader=lambda: model, warmup=False)

    result = await provider.synthesize("Привет", "baya", tmp_path / "reply.wav")

    assert result.voice == "baya"
    assert model.calls == ["Привет"]


@pytest.mark.anyio
async def test_silero_synthesize_atomically_creates_wav(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install_fake_torch(monkeypatch)
    provider = SileroTTSProvider(model_loader=FakeSileroModel, warmup=False)
    output_path = tmp_path / "reply.wav"

    result = await provider.synthesize("Привет", "ignored", output_path)

    assert result.provider == "silero"
    assert result.voice == "xenia"
    assert result.audio_path == output_path
    assert output_path.exists()
    assert not list(tmp_path.glob("*.tmp.wav"))


@pytest.mark.anyio
async def test_silero_synthesize_removes_temp_file_on_cancel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install_fake_torch(monkeypatch)
    provider = SileroTTSProvider(
        model_loader=lambda: FakeSileroModel(delay=0.2),
        warmup=False,
        timeout_seconds=2,
    )
    task = asyncio.create_task(provider.synthesize("Привет", "ignored", tmp_path / "reply.wav"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not list(tmp_path.glob("*.tmp.wav"))


def test_silero_unknown_speaker_returns_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_torch(monkeypatch)
    provider = SileroTTSProvider(
        speaker="unknown",
        model_loader=FakeSileroModel,
        warmup=False,
    )

    with pytest.raises(RuntimeError, match="Unknown Silero speaker"):
        asyncio.run(provider.preload())


def test_silero_cuda_requires_available_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_torch(monkeypatch, cuda_available=False)
    provider = SileroTTSProvider(device="cuda", model_loader=FakeSileroModel, warmup=False)

    with pytest.raises(RuntimeError, match="CUDA is not available"):
        asyncio.run(provider.preload())


def test_next_tts_path_uses_wav_for_silero(tmp_path: Path) -> None:
    settings = Settings(voice_tts_provider="silero", voice_audio_dir=str(tmp_path / "audio"))
    service = VoiceService(settings)

    assert service.next_tts_path("silero").suffix == ".wav"


@pytest.mark.parametrize("provider_name", ["edge_tts", "auto"])
def test_edge_and_auto_tts_providers_are_not_supported(provider_name: str, tmp_path: Path) -> None:
    settings = Settings(voice_tts_provider=provider_name, voice_audio_dir=str(tmp_path / "audio"))

    with pytest.raises(ValueError, match="Unsupported TTS provider"):
        VoiceService(settings)
