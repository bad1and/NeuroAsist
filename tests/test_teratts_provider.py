from __future__ import annotations

import asyncio
import io
import wave

import numpy as np
import pytest

from apps.backend.app.voice.providers import TTSRequest
from apps.backend.app.voice.style import VoiceExpressionLevel, VoiceStyle
from apps.backend.app.voice.teratts_normalizer import normalize_for_teratts
from apps.backend.app.voice.teratts_provider import (
    TERATTS_REVISION,
    TERATTS_SAMPLE_RATE,
    TeraTTSProvider,
)


class FakeTeraModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def generate_speech_stream(self, text: str, **kwargs):
        self.calls.append({"text": text, **kwargs})
        yield np.zeros(441, dtype=np.float32)
        yield np.zeros(441, dtype=np.float32)

    def close(self) -> None:
        self.closed = True


def test_normalizer_emits_one_balanced_ru_span() -> None:
    normalized = normalize_for_teratts(
        "На 18 августа в 18:00 выходит FastAPI версии v2.5.1 <en>backend</en>."
    )
    assert normalized.startswith("<ru>") and normalized.endswith("</ru>")
    assert normalized.count("<ru>") == normalized.count("</ru>") == 1
    assert "<en>" not in normalized
    assert "восемнадцатое августа" in normalized
    assert "Фаст+АПИ" in normalized
    assert "версия два точка пять точка один" in normalized


def test_normalizer_converts_editor_stress_and_unicode_dash() -> None:
    normalized = normalize_for_teratts("Мука́ — это продукт…")

    assert normalized == "<ru>Мук+а - это продукт…</ru>"
    assert "\u0301" not in normalized


def test_teratts_provider_maps_style_and_tempo_and_writes_44100_wav() -> None:
    model = FakeTeraModel()

    def loader(**kwargs):
        assert kwargs["revision"] == TERATTS_REVISION
        assert kwargs["provider"] == "CPUExecutionProvider"
        return model

    provider = TeraTTSProvider(
        voice="ru_f1",
        warmup=False,
        model_loader=loader,
        audio_postprocessing_enabled=False,
    )
    request = TTSRequest(
        text="Привет!",
        language="ru",
        voice="ru_f1",
        style=VoiceStyle.ENERGETIC,
        tempo=1.05,
        pause_before_ms=10,
        pause_after_ms=20,
    )
    chunks = asyncio.run(_collect(provider, request))

    assert len(chunks) == 1
    with wave.open(io.BytesIO(chunks[0].data), "rb") as audio:
        assert audio.getframerate() == TERATTS_SAMPLE_RATE
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getnframes() == 441 + 441 + round(TERATTS_SAMPLE_RATE * 0.03)
    assert model.calls[0]["voice"] == "ru_f1"
    assert model.calls[0]["seed"] == 1234
    assert model.calls[0]["duration_scale"] == pytest.approx(0.8381, rel=0.01)
    assert chunks[0].metadata["sample_rate"] == TERATTS_SAMPLE_RATE
    assert chunks[0].metadata["native_stream"] is True


def test_teratts_provider_loads_once_under_concurrent_preload() -> None:
    calls = 0

    def loader(**kwargs):
        nonlocal calls
        calls += 1
        return FakeTeraModel()

    provider = TeraTTSProvider(model_loader=loader, warmup=False)
    asyncio.run(_preload_twice(provider))
    assert calls == 1


def test_teratts_provider_closes_injected_model() -> None:
    model = FakeTeraModel()
    provider = TeraTTSProvider(model_loader=lambda **_kwargs: model, warmup=False)

    asyncio.run(provider.preload())
    asyncio.run(provider.close())

    assert model.closed is True
    assert provider.metadata["loaded"] is False


async def _collect(provider: TeraTTSProvider, request: TTSRequest):
    return [chunk async for chunk in provider.stream(request)]


async def _preload_twice(provider: TeraTTSProvider) -> None:
    await asyncio.gather(provider.preload(), provider.preload())
