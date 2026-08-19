from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from apps.backend.app.core.config import Settings
from apps.backend.app.voice.audio import Pcm16Audio
from apps.backend.app.voice.providers import (
    AudioChunk,
    FallbackSTTProvider,
    FasterWhisperSTTProvider,
    GigaAMSTTProvider,
    MockTTSProvider,
    Qwen3ASRProvider,
    STTProvider,
    STTResult,
    TTSProvider,
    TTSRequest,
    apply_wav_delivery,
    one_pole_highpass,
    split_tts_chunks,
    waveform_to_wav_bytes,
)
from apps.backend.app.voice.service import VoiceService
from apps.backend.app.voice.lexicon import load_pronunciations, save_pronunciations
from apps.backend.app.voice.teratts_normalizer import normalize_for_teratts
from apps.backend.app.voice.style import VoiceStyle, resolve_voice_style


def _spoken_ssml(value: str) -> str:
    return value.strip()


def test_atempo_changes_duration_without_changing_pitch() -> None:
    sample_rate = 48000
    source = (
        np.sin(2 * np.pi * 440 * np.arange(sample_rate) / sample_rate) * 12000
    ).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(source.tobytes())

    delivered = apply_wav_delivery(buffer.getvalue(), tempo=1.05)
    with wave.open(io.BytesIO(delivered), "rb") as audio:
        samples = np.frombuffer(
            audio.readframes(audio.getnframes()), dtype="<i2"
        ).astype(float)
        duration = audio.getnframes() / audio.getframerate()
    frequencies = np.fft.rfftfreq(len(samples), 1 / sample_rate)
    peak_hz = frequencies[np.argmax(np.abs(np.fft.rfft(samples)))]

    assert duration == pytest.approx(1 / 1.05, rel=0.02)
    assert peak_hz == pytest.approx(440, rel=0.01)


def test_tts_cleanup_keeps_only_recent_wavs(tmp_path) -> None:
    settings = Settings(
        voice_audio_dir=str(tmp_path / "audio"),
        voice_stt_provider="mock",
        voice_tts_provider="mock",
    )
    service = VoiceService(settings)
    tts_dir = settings.voice_audio_path / "tts"
    tts_dir.mkdir(parents=True)
    old_wav = tts_dir / "old.wav"
    fresh_wav = tts_dir / "fresh.wav"
    old_wav.write_bytes(b"old")
    fresh_wav.write_bytes(b"fresh")
    old_timestamp = time.time() - 121
    os.utime(old_wav, (old_timestamp, old_timestamp))

    assert service.cleanup_tts_audio(max_age_seconds=120) == 1
    assert not old_wav.exists()
    assert fresh_wav.exists()


def test_default_voice_settings_prioritize_full_live_thoughts_and_adaptive_prosody() -> None:
    assert Settings.model_fields["voice_live_safe_segment_words"].default == 18
    assert Settings.model_fields["voice_tts_adaptive_prosody"].default is True


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


def test_gigaam_transcribes_with_selected_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_calls: list[dict[str, object]] = []

    class FakeGigaAMModel:
        def transcribe(self, audio_path: str):
            assert audio_path.endswith("input.wav")
            return SimpleNamespace(text="точная русская расшифровка")

    def load_model(model_name: str, **kwargs):
        load_calls.append({"model": model_name, **kwargs})
        return FakeGigaAMModel()

    monkeypatch.setitem(sys.modules, "gigaam", SimpleNamespace(load_model=load_model))
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"fake")
    provider = GigaAMSTTProvider("v3_rnnt", "cpu")

    result = asyncio.run(provider.transcribe(audio_path, "ru"))

    assert result.text == "точная русская расшифровка"
    assert result.provider == "gigaam"
    assert result.model == "v3_rnnt"
    assert load_calls == [
        {
            "model": "v3_rnnt",
            "device": "cpu",
            "fp16_encoder": False,
            "use_flash": False,
        }
    ]


def test_gigaam_auto_falls_back_to_cpu_during_load(monkeypatch: pytest.MonkeyPatch) -> None:
    devices: list[str] = []

    def load_model(model_name: str, *, device: str, **kwargs):
        devices.append(device)
        if device == "cuda":
            raise RuntimeError("CUDA out of memory")
        return SimpleNamespace(transcribe=lambda path: SimpleNamespace(text="готово"))

    monkeypatch.setitem(sys.modules, "gigaam", SimpleNamespace(load_model=load_model))
    provider = GigaAMSTTProvider("v3_rnnt", "auto")

    asyncio.run(provider.preload())

    assert devices == ["cuda", "cpu"]
    assert provider._selected_device == "cpu"


def test_qwen3_asr_provider_is_lazy_and_uses_russian_language_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeModel:
        def transcribe(self, **kwargs):
            calls.append(kwargs)
            return [SimpleNamespace(language="Russian", text="проверка qwen")]

    class FakeQwen:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs):
            calls.append({"model": model_name, **kwargs})
            return FakeModel()

    monkeypatch.setitem(sys.modules, "qwen_asr", SimpleNamespace(Qwen3ASRModel=FakeQwen))
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"fake")
    provider = Qwen3ASRProvider("Qwen/Qwen3-ASR-0.6B", "cpu")

    result = asyncio.run(provider.transcribe(audio_path, "ru"))

    assert result.text == "проверка qwen"
    assert result.provider == "qwen3_asr"
    assert result.model == "Qwen/Qwen3-ASR-0.6B"
    assert calls[0]["model"] == "Qwen/Qwen3-ASR-0.6B"
    assert calls[1] == {"audio": str(audio_path), "language": "Russian"}


def test_stt_fallback_runs_only_for_low_snr() -> None:
    class Primary(STTProvider):
        async def transcribe(self, audio_path: Path, language: str) -> STTResult:
            return STTResult("первичный", language, 1, "primary")

        async def transcribe_pcm16(self, audio: Pcm16Audio, language: str) -> STTResult:
            return STTResult("первичный", language, 1, "primary")

    class Secondary(STTProvider):
        async def transcribe(self, audio_path: Path, language: str) -> STTResult:
            return STTResult("вторичный", language, 1, "secondary")

        async def transcribe_pcm16(self, audio: Pcm16Audio, language: str) -> STTResult:
            return STTResult("вторичный", language, 1, "secondary")

    provider = FallbackSTTProvider(Primary(), Secondary(), min_rms=.01)
    loud = Pcm16Audio((np.full(1600, 3000, dtype="<i2")).tobytes())
    quiet = Pcm16Audio((np.full(1600, 100, dtype="<i2")).tobytes())

    loud_result = asyncio.run(provider.transcribe_pcm16(loud, "ru"))
    quiet_result = asyncio.run(provider.transcribe_pcm16(quiet, "ru"))

    assert loud_result.provider == "primary"
    assert quiet_result.provider == "secondary"
    assert quiet_result.fallback is True
    assert quiet_result.fallback_reason == "low_snr"


def test_gigaam_long_audio_split_preserves_pcm_and_stays_under_limit() -> None:
    provider = GigaAMSTTProvider("v3_rnnt", "cpu")
    samples = np.full(30 * 16000, 1000, dtype="<i2")
    samples[18 * 16000 : 18 * 16000 + 1600] = 0
    pcm16 = samples.tobytes()

    chunks = provider._split_pcm16_on_quiet(pcm16)

    assert len(chunks) == 2
    assert b"".join(chunks) == pcm16
    assert all(len(chunk) // 2 <= 24 * 16000 for chunk in chunks)
    assert abs((len(chunks[0]) // 2) - int(18.05 * 16000)) <= 1600


def test_one_pole_highpass_matches_the_scalar_recurrence() -> None:
    sample_rate = 48000
    samples = (
        np.random.default_rng(7).standard_normal(sample_rate) * 0.3
    ).astype(np.float32)

    def scalar(cutoff_hz: float) -> np.ndarray:
        rc = 1.0 / (2.0 * np.pi * cutoff_hz)
        alpha = rc / (rc + 1.0 / sample_rate)
        expected = np.empty_like(samples)
        expected[0] = samples[0]
        previous_input = float(samples[0])
        previous_output = float(samples[0])
        for index in range(1, len(samples)):
            current = alpha * (previous_output + float(samples[index]) - previous_input)
            expected[index] = current
            previous_input = float(samples[index])
            previous_output = current
        return expected

    for cutoff_hz in (20.0, 60.0, 1000.0):
        filtered = one_pole_highpass(samples, sample_rate, cutoff_hz)
        # Well below the 1/32767 step the waveform is quantised to on the way out.
        assert np.max(np.abs(filtered - scalar(cutoff_hz))) < 1e-7


def test_one_pole_highpass_passes_through_degenerate_input() -> None:
    samples = np.array([0.5, -0.5], dtype=np.float32)
    single = samples[:1]

    assert one_pole_highpass(samples, 48000, 0.0) is samples
    assert one_pole_highpass(samples, 0, 60.0) is samples
    assert one_pole_highpass(single, 48000, 60.0) is single


def test_waveform_to_wav_bytes_clamps_and_writes_pcm16_wav() -> None:
    wav_bytes = waveform_to_wav_bytes(np.array([-2.0, -0.5, 0.0, 0.5, 2.0]), 24000)

    with wave.open(__import__("io").BytesIO(wav_bytes), "rb") as audio:
        assert audio.getframerate() == 24000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")

    assert pcm.tolist() == [-32767, -16383, 0, 16383, 32767]



def test_pronunciation_dictionary_can_be_saved_and_reloaded(tmp_path: Path) -> None:
    dictionary = tmp_path / "pronunciations.json"

    pronunciations = save_pronunciations(dictionary, {"Luka": "Лука", "API": "эй пи ай"})

    assert pronunciations["Luka"] == "Лука"
    assert load_pronunciations(dictionary)["API"] == "эй пи ай"
    assert normalize_for_teratts(
        "OpenAI API, Python и GitHub",
        pronunciations=load_pronunciations(dictionary),
    ).startswith("<ru>")


def test_custom_pronunciation_overrides_builtin_regardless_of_case(tmp_path: Path) -> None:
    dictionary = tmp_path / "pronunciations.json"

    pronunciations = save_pronunciations(dictionary, {"КАК-ТО": "к+ак-т+о"})

    assert pronunciations["КАК-ТО"] == "к+ак-т+о"
    assert "как-то" not in pronunciations
    assert normalize_for_teratts(
        "Как-то", pronunciations=load_pronunciations(dictionary)
    ) == "<ru>к+ак-т+о</ru>"



def test_next_tts_path_uses_wav_for_teratts(tmp_path: Path) -> None:
    settings = Settings(voice_tts_provider="teratts", voice_audio_dir=str(tmp_path / "audio"))
    service = VoiceService(settings)

    assert service.next_tts_path("teratts").suffix == ".wav"


@pytest.mark.parametrize("provider_name", ["edge_tts", "auto", "chatterbox"])
def test_edge_and_auto_tts_providers_are_not_supported(provider_name: str, tmp_path: Path) -> None:
    settings = Settings(voice_tts_provider=provider_name, voice_audio_dir=str(tmp_path / "audio"))

    with pytest.raises(ValueError, match="Unsupported TTS provider"):
        VoiceService(settings)


def test_teratts_normalizer_keeps_one_balanced_ru_span() -> None:
    normalized = normalize_for_teratts("FastAPI <en>backend</en> версии v2.5.1.")
    assert normalized.count("<ru>") == normalized.count("</ru>") == 1
    assert "<en>" not in normalized
    assert "Фаст+АПИ" in normalized


def test_auto_style_resolves_to_energetic_for_happy_fast_delivery() -> None:
    assert resolve_voice_style(VoiceStyle.AUTO, emotion="happy", pace="fast") is VoiceStyle.ENERGETIC
