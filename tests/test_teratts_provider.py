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
    assert "версии два точка пять точка один" in normalized


def test_normalizer_converts_editor_stress_and_unicode_dash() -> None:
    normalized = normalize_for_teratts("Мука́ — это продукт…")

    assert normalized == "<ru>Мук+а; это продукт…</ru>"
    assert "\u0301" not in normalized


def test_normalizer_preserves_deliberate_homograph_stress_for_wordplay() -> None:
    assert normalize_for_teratts("за́мок и замо́к") == "<ru>з+амок и зам+ок</ru>"


@pytest.mark.parametrize(
    ("source", "spoken"),
    [
        ("В 2024 году", "в две тысячи двадцать четвёртом году"),
        ("К 2027 году", "к две тысячи двадцать седьмому году"),
        ("С 2020 по 2024 годы", "с две тысячи двадцатого по две тысячи двадцать четвёртый год"),
        ("Она заняла 1-е место, затем 2 место", "первое место, затем второе место"),
        ("Она была на 3 месте", "на третьем месте"),
        ("Поднялась с 5 места", "с пятого места"),
        ("Диапазон 5–10 минут", "от пяти до десяти минут"),
        ("От 20 до 30 секунд", "от двадцати до тридцати секунд"),
        ("Рост 15–20%", "от пятнадцати до двадцати процентов"),
        ("Вероятность 3,14%", "три целых четырнадцать сотых процента"),
        ("Встреча 28.09.2026", "двадцать восьмого сентября две тысячи двадцать шестого года"),
        ("Встреча 2026-09-28", "двадцать восьмого сентября две тысячи двадцать шестого года"),
        ("Встреча 28/09/2026", "двадцать восьмого сентября две тысячи двадцать шестого года"),
        ("Сейчас 1:01", "один час одна минута"),
        ("Перенеси на 3 сентября", "на третье сентября"),
        ("Перенеси на 23 сентября", "на двадцать третье сентября"),
    ],
)
def test_normalizer_expands_contextual_numbers(source: str, spoken: str) -> None:
    assert spoken.lower() in normalize_for_teratts(source).lower()


def test_normalizer_turns_prose_punctuation_into_stable_prosody() -> None:
    normalized = normalize_for_teratts("Я проверила — всё работает... Правда?!")

    assert normalized == "<ru>Я проверила; всё работает… Правда?</ru>"


def test_normalizer_speaks_arithmetic_operators_without_confusing_stress_marks() -> None:
    assert normalize_for_teratts("2 + 2 = 4") == "<ru>два плюс два равно четыре</ru>"
    assert normalize_for_teratts("5 - 3 = 2") == "<ru>пять минус три равно два</ru>"


def test_teratts_provider_maps_style_and_tempo_and_writes_44100_wav() -> None:
    model = FakeTeraModel()

    def loader(**kwargs):
        assert kwargs["revision"] == TERATTS_REVISION
        assert kwargs["provider"] == "CPUExecutionProvider"
        assert kwargs["ruaccent_mode"] == "full"
        assert kwargs["russian_stress"] is True
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
