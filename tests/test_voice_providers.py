import asyncio
import contextlib
import io
import logging
import os
import re
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
    Qwen3ASRProvider,
    MockTTSProvider,
    SileroTTSProvider,
    TTSProvider,
    TTSRequest,
    STTProvider,
    STTResult,
    configure_cmudict,
    normalize_russian_tts_text,
    prepare_english_tts_text,
    split_multilingual_tts_segments,
    split_tts_chunks,
    waveform_to_wav_bytes,
    apply_wav_delivery,
)
from apps.backend.app.voice.service import VoiceService
from apps.backend.app.voice.lexicon import load_pronunciations, save_pronunciations
from apps.backend.app.voice.style import VoiceExpressionLevel, VoiceStyle, make_silero_ssml, profile_for, resolve_voice_style


def _spoken_ssml(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


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


def test_waveform_to_wav_bytes_clamps_and_writes_pcm16_wav() -> None:
    wav_bytes = waveform_to_wav_bytes(np.array([-2.0, -0.5, 0.0, 0.5, 2.0]), 24000)

    with wave.open(__import__("io").BytesIO(wav_bytes), "rb") as audio:
        assert audio.getframerate() == 24000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")

    assert pcm.tolist() == [-32767, -16383, 0, 16383, 32767]


def test_russian_tts_normalization_expands_numbers_and_common_english_words() -> None:
    text = "NeuroAsist версии 2.5 использует OpenAI API, GPU на 37% и порт 8080."

    normalized = normalize_russian_tts_text(text)

    assert normalized == (
        "нейро асист версии два точка пять использует оупен эй ай эй пи ай, "
        "джи пи ю на тридцать семь процентов и порт восемьдесят, восемьдесят."
    )


def test_russian_tts_normalization_reads_leading_zeroes_digit_by_digit() -> None:
    assert normalize_russian_tts_text("Код 007") == "Код ноль ноль семь"


def test_russian_tts_normalization_handles_versions_and_ip_addresses() -> None:
    assert normalize_russian_tts_text("Версия 1.2.10", transliterate_latin=False) == (
        "Версия один точка два точка десять"
    )
    assert normalize_russian_tts_text("Сервер 192.168.1.1", transliterate_latin=False) == (
        "Сервер сто девяносто два точка сто шестьдесят восемь точка один точка один"
    )


def test_russian_tts_normalization_preserves_hyphenated_words_and_forces_manual_stress() -> None:
    accentor_calls: list[str] = []

    def accent(text: str) -> str:
        accentor_calls.append(text)
        return text.replace("всё-таки", "вс+ё-т+аки")

    normalized = normalize_russian_tts_text(
        "Как‑то всё–таки случилось.",
        transliterate_latin=False,
        pronunciations={"Как-то": "ка́к-то"},
        stress_accentor=accent,
    )

    assert normalized == "к+ак-то вс+ё-т+аки случилось."
    assert all("Как-то" not in call for call in accentor_calls)


def test_russian_tts_normalization_accepts_silero_plus_stress_notation() -> None:
    assert normalize_russian_tts_text(
        "Мука и замок",
        transliterate_latin=False,
        pronunciations={"Мука": "м+ука", "замок": "з+амок"},
    ) == "м+ука и з+амок"


def test_russian_tts_normalization_declines_years_and_transcribes_technical_english() -> None:
    assert normalize_russian_tts_text("Я начала в 2015 году") == (
        "Я начала в две тысячи пятнадцатом году"
    )


def test_russian_tts_normalization_expands_numeric_date() -> None:
    assert normalize_russian_tts_text("Встреча 25.07.2026", transliterate_latin=False) == (
        "Встреча двадцать пятое июля две тысячи двадцать шестого года"
    )


def test_silero_ssml_uses_restrained_adaptive_prosody_and_escapes_text() -> None:
    ssml = make_silero_ssml("Громче: но сейчас, потому что <сейчас>!", VoiceStyle.ENERGETIC)

    assert "&lt;сейчас&gt;!" in ssml
    assert "<prosody" not in ssml
    assert '<break time="50ms"/>' in ssml
    assert '<break time="35ms"/>' in ssml
    assert "<break time=\"95ms\"/>" in ssml
    assert profile_for(VoiceStyle.CALM).intensity == 3
    assert profile_for(VoiceStyle.NORMAL).intensity == 3
    assert profile_for(VoiceStyle.ENERGETIC).intensity == 3
    assert profile_for(VoiceStyle.ENERGETIC, VoiceExpressionLevel.MINIMAL).intensity == 3
    assert profile_for(VoiceStyle.ENERGETIC, VoiceExpressionLevel.NOTICEABLE).intensity == 3
    assert resolve_voice_style(VoiceStyle.AUTO, emotion="sad") is VoiceStyle.CALM
    assert resolve_voice_style(VoiceStyle.ASSERTIVE, emotion="happy") is VoiceStyle.ASSERTIVE
    assert resolve_voice_style(VoiceStyle.AUTO, emphasis=0.8) is VoiceStyle.ASSERTIVE


def test_silero_ssml_can_disable_adaptive_prosody_for_a_baseline() -> None:
    ssml = make_silero_ssml(
        "Громче: но сейчас!", VoiceStyle.ENERGETIC, adaptive_prosody=False
    )

    assert "<prosody" not in ssml
    assert '<break time="50ms"/>' not in ssml
    assert '<break time="95ms"/>' in ssml


def test_pronunciation_dictionary_can_be_saved_and_reloaded(tmp_path: Path) -> None:
    dictionary = tmp_path / "pronunciations.json"

    pronunciations = save_pronunciations(dictionary, {"Luka": "Лука", "API": "эй пи ай"})

    assert pronunciations["Luka"] == "Лука"
    assert load_pronunciations(dictionary)["API"] == "эй пи ай"
    assert normalize_russian_tts_text("OpenAI API, Python и GitHub") == (
        "оупен эй ай эй пи ай, пайтон и гитхаб"
    )
    assert prepare_english_tts_text("OpenAI API, Python and GitHub") == (
        "Open A I A P I, Pie thon and Git Hub"
    )


def test_custom_pronunciation_overrides_builtin_regardless_of_case(tmp_path: Path) -> None:
    dictionary = tmp_path / "pronunciations.json"

    pronunciations = save_pronunciations(dictionary, {"КАК-ТО": "к+ак-т+о"})

    assert pronunciations["КАК-ТО"] == "к+ак-т+о"
    assert "как-то" not in pronunciations
    assert normalize_russian_tts_text(
        "Как-то", transliterate_latin=False, pronunciations=load_pronunciations(dictionary)
    ) == "к+ак-т+о"


def test_russian_tts_uses_cmu_pronunciation_for_regular_english(tmp_path: Path) -> None:
    dictionary = tmp_path / "cmudict.dict"
    dictionary.write_text(
        "hello HH AH0 L OW1\nworld W ER1 L D\nvoice V OY1 S\n",
        encoding="utf-8",
    )
    configure_cmudict(dictionary)

    assert normalize_russian_tts_text("Hello world, voice") == "хэлоу уэрлд, войс"


def test_multilingual_tts_segments_keep_english_native() -> None:
    assert split_multilingual_tts_segments(
        "Запусти Python 3.12 через OpenAI API на порту 8080."
    ) == [
        ("ru", "Запусти"),
        ("en", "Python 3.12"),
        ("ru", "через"),
        ("en", "OpenAI API"),
        ("ru", "на порту восемьдесят, восемьдесят."),
    ]




class FakeSileroModel:
    speakers = ["xenia", "baya"]

    def __init__(self, delay: float = 0.0) -> None:
        self.calls: list[str] = []
        self.delay = delay
        self.to_device: str | None = None

    def to(self, device: str):
        self.to_device = device
        return self

    def apply_tts(self, *, text: str | None = None, ssml_text: str | None = None, speaker: str, sample_rate: int, intensity: int = 3):
        if self.delay:
            import time

            time.sleep(self.delay)
        self.calls.append(text or ssml_text or "")
        return np.array([0.0, 0.2, -0.2, 0.0], dtype=np.float32)


class InPlaceDeviceSileroModel(FakeSileroModel):
    def to(self, device: str):
        self.to_device = device
        return None


class FakeEnglishSileroModel(FakeSileroModel):
    speakers = ["en_0"]


class FakeVoiceConverter:
    sample_rate = 22050

    def __init__(self) -> None:
        self.loads = 0
        self.calls: list[tuple[int, int]] = []

    def load(self) -> None:
        self.loads += 1

    def convert(self, waveform, sample_rate: int):
        self.calls.append((len(waveform), sample_rate))
        return waveform


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


def test_silero_uses_local_stress_accentor_before_synthesis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_fake_torch(monkeypatch)
    model = FakeSileroModel()
    loads = 0

    def load_accentor():
        nonlocal loads
        loads += 1
        return lambda text: text.replace("мама", "м+ама")

    provider = SileroTTSProvider(
        model_loader=lambda: model,
        stress_accentor_loader=load_accentor,
        warmup=False,
    )

    asyncio.run(provider.synthesize("мама", "xenia", tmp_path / "reply.wav"))

    assert loads == 1
    assert [_spoken_ssml(call) for call in model.calls] == ["м+ама"]
    assert provider.metadata["stress"] == "ready"


def test_silero_context_pronunciation_override_bypasses_automatic_stress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_fake_torch(monkeypatch)
    model = FakeSileroModel()

    provider = SileroTTSProvider(
        model_loader=lambda: model,
        stress_accentor_loader=lambda: (lambda text: text.replace("замок", "зам+ок")),
        warmup=False,
    )
    provider.set_pronunciations({
        "На двери новый замок": "На двери новый з+амок",
    })

    asyncio.run(provider.synthesize("На двери новый замок.", "baya", tmp_path / "reply.wav"))

    assert [_spoken_ssml(call) for call in model.calls] == ["На двери новый з+амок."]


def test_silero_stress_failure_keeps_builtin_stress_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    install_fake_torch(monkeypatch)
    model = FakeSileroModel()

    def fail_to_load():
        raise RuntimeError("missing model")

    provider = SileroTTSProvider(
        model_loader=lambda: model,
        stress_accentor_loader=fail_to_load,
        warmup=False,
    )
    with caplog.at_level(logging.WARNING):
        asyncio.run(provider.synthesize("Привет", "xenia", tmp_path / "reply.wav"))

    assert [_spoken_ssml(call) for call in model.calls] == ["Привет"]
    assert provider.metadata["stress"] == "fallback"
    assert "falling back to built-in Silero stress" in caplog.text


def test_silero_audio_postprocessing_removes_offset_and_avoids_clicks() -> None:
    provider = SileroTTSProvider(stress_enabled=False, sample_rate=48000)
    time_axis = np.arange(480, dtype=np.float32) / provider.sample_rate
    waveform = 0.25 + 0.2 * np.sin(2 * np.pi * 220 * time_axis)
    waveform[2] = np.nan
    waveform[3] = np.inf

    normalized, metrics = provider._postprocess_speech_waveform(waveform, provider.sample_rate)

    assert np.isfinite(normalized).all()
    assert abs(float(metrics["output"]["dc_offset"])) < abs(float(metrics["input"]["dc_offset"]))
    assert normalized[0] == pytest.approx(0.0)
    assert normalized[-1] == pytest.approx(0.0)
    assert int(metrics["output"]["clipped_samples"]) == 0
    assert float(np.max(np.abs(normalized))) <= 10 ** (-1 / 20) + 1e-6


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

    assert [_spoken_ssml(call) for call in model.calls] == ["Привет."]


def test_silero_accepts_in_place_model_to(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_torch(monkeypatch)
    model = InPlaceDeviceSileroModel()
    provider = SileroTTSProvider(model_loader=lambda: model, warmup=True)

    asyncio.run(provider.preload())

    assert model.to_device == "cpu"
    assert [_spoken_ssml(call) for call in model.calls] == ["Привет."]


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
async def test_silero_normalizes_text_and_applies_optional_cpu_voice_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_torch(monkeypatch)
    model = FakeSileroModel()
    converter = FakeVoiceConverter()
    provider = SileroTTSProvider(
        model_loader=lambda: model,
        warmup=False,
        openvoice_enabled=True,
        openvoice_reference_audio_path=Path("voice.wav"),
        voice_converter_loader=lambda: converter,
    )

    chunks = [
        chunk
        async for chunk in provider.stream(
            TTSRequest("OpenAI API на порту 8080", "ru", "xenia")
        )
    ]

    assert [_spoken_ssml(call) for call in model.calls] == ["оупен эй ай эй пи ай на порту восемьдесят, восемьдесят"]
    assert converter.loads == 1
    assert converter.calls == [(4, 24000)]
    assert chunks[0].metadata["sample_rate"] == 22050
    assert chunks[0].metadata["voice_conversion"] is True
    with wave.open(__import__("io").BytesIO(chunks[0].data), "rb") as audio:
        assert audio.getframerate() == 22050


@pytest.mark.anyio
async def test_silero_can_synthesize_english_runs_natively_before_voice_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_torch(monkeypatch)
    russian_model = FakeSileroModel()
    english_model = FakeEnglishSileroModel()
    converter = FakeVoiceConverter()
    provider = SileroTTSProvider(
        model_loader=lambda: russian_model,
        english_model_loader=lambda: english_model,
        native_english=True,
        warmup=False,
        openvoice_enabled=True,
        openvoice_reference_audio_path=Path("voice.wav"),
        voice_converter_loader=lambda: converter,
    )

    chunks = [
        chunk
        async for chunk in provider.stream(
            TTSRequest("Запусти OpenAI API на порту 8080", "ru", "xenia")
        )
    ]

    assert [_spoken_ssml(call) for call in russian_model.calls] == ["Запусти", "на порту восемьдесят, восемьдесят"]
    assert english_model.calls == ["Open A I A P I"]
    assert chunks[0].metadata["native_english"] is True


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
    assert [_spoken_ssml(call) for call in model.calls] == ["Привет"]


def test_silero_rejects_male_runtime_voice_and_falls_back_to_configured_female() -> None:
    provider = SileroTTSProvider(speaker="xenia", warmup=False)

    assert provider.available_speakers == ["xenia", "baya", "kseniya"]
    assert provider.resolve_voice("ru", "aidar") == "xenia"
    assert provider.resolve_voice("ru", "eugene") == "xenia"


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


@pytest.mark.parametrize("provider_name", ["edge_tts", "auto", "chatterbox"])
def test_edge_and_auto_tts_providers_are_not_supported(provider_name: str, tmp_path: Path) -> None:
    settings = Settings(voice_tts_provider=provider_name, voice_audio_dir=str(tmp_path / "audio"))

    with pytest.raises(ValueError, match="Unsupported TTS provider"):
        VoiceService(settings)
