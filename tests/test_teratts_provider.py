from __future__ import annotations

import asyncio
import io
import threading
from types import SimpleNamespace
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


@pytest.mark.parametrize(("text", "spoken"), [
    ("5 - 3", "пять минус три"),
    ("5-3", "пять минус три"),
    ("5−3", "пять минус три"),
    ("8 ÷ 2 = 4", "восемь разделить на два равно четыре"),
    ("2 + (-3) = -1", "два плюс (минус три) равно минус один"),
    ("2*(3+4)=14", "два умножить на (три плюс четыре) равно четырнадцать"),
    ("(5-3)*2=4", "(пять минус три) умножить на два равно четыре"),
    ("2-(-3)=5", "два минус (минус три) равно пять"),
    ("2^3=8", "два в степени три равно восемь"),
    ("2**3=8", "два в степени три равно восемь"),
    ("3,5 + 1,5 = 5", "три целых пять десятых плюс одна целая пять десятых равно пять"),
])
def test_math_notation_is_spoken_as_operations(text, spoken) -> None:
    from apps.backend.app.voice.text import TextNormalizer
    assert normalize_for_teratts(TextNormalizer().normalize(text)) == f"<ru>{spoken}</ru>"


def test_math_normalization_keeps_explicit_ranges_and_stress():
    assert normalize_for_teratts("от 5 - 10 минут") == '<ru>от пяти до десяти минут</ru>'
    assert normalize_for_teratts("Рост 5–10%") == '<ru>Рост от пяти до десяти процентов</ru>'
    assert normalize_for_teratts("за́мок и замо́к") == '<ru>з+амок и зам+ок</ru>'


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


def test_dictionary_overrides_tech_terms_as_whole_phrases_without_cascading() -> None:
    assert normalize_for_teratts(
        "API и OpenAI. микрокот и кот. кот дома.",
        {"API": "эй пи ай", "OpenAI": "Оупен Эй Ай", "кот": "кит", "кот дома": "кот тут"},
    ) == "<ru>эй пи ай и Оупен Эй Ай. микрокот и кит. кот тут.</ru>"


def test_dictionary_preserves_acute_accents_and_literal_replacements() -> None:
    assert normalize_for_teratts("замок", {"замок": "за́мок"}) == "<ru>з+амок</ru>"
    assert normalize_for_teratts("путь", {"путь": r"C:\test"}) == r"<ru>C: \test</ru>"


def test_provider_loads_saved_pronunciations_on_creation(tmp_path) -> None:
    path = tmp_path / "pronunciations.json"
    path.write_text('{"pronunciations": {"API": "эй пи ай"}}', encoding="utf-8")
    model = FakeTeraModel()
    provider = TeraTTSProvider(model_loader=lambda: model, warmup=False,
                               pronunciation_dictionary_path=path)
    asyncio.run(_collect(provider, TTSRequest(text="API", language="ru", voice="ru_f1")))
    assert model.calls[0]["text"] == "<ru>эй пи ай</ru>"


def test_explicit_stress_does_not_disable_automatic_accents_elsewhere() -> None:
    calls = []

    def accent(text):
        calls.append(text)
        return text.replace("открыла", "откр+ыла").replace("инструкцию", "инстр+укцию")

    provider = TeraTTSProvider(warmup=False)
    provider._model = SimpleNamespace(runtime=SimpleNamespace(accentizer=SimpleNamespace(process_all=accent)))
    result = provider._prepare_model_text("<ru>Я открыла Гитх+аб и инструкцию…</ru>")
    assert result == "<ru>Я откр+ыла Гитх+аб и инстр+укцию...</ru>"
    assert calls == ["Я открыла", "и инструкцию..."]


def test_ellipsis_survives_the_model_accentor_punctuation_filter() -> None:
    provider = TeraTTSProvider(warmup=False)
    assert provider._prepare_model_text("<ru>Подожди… Теперь можно.</ru>") == "<ru>Подожди... Теперь можно.</ru>"


@pytest.mark.parametrize(("source", "spoken"), [
    ("Цена 1500–2000 рублей", "Цена от одной тысячи пятисот до двух тысяч рублей"),
    ("Убыток -5%", "Убыток минус пять процентов"),
    ("Температура −2,5", "Температура минус две целых пять десятых"),
    ("Версия 3.12", "Версия три точка двенадцать"),
    ("Версия 3.12.", "Версия три точка двенадцать."),
    ("Осталось 12.", "Осталось двенадцать."),
    ("Значение -0,5.", "Значение минус ноль целых пять десятых."),
    ("Падение -0,5%.", "Падение минус ноль целых пять десятых процента."),
    ("Т. е. всё готово и т. д.", "то есть всё готово и так далее"),
])
def test_spoken_numbers_and_abbreviations_keep_their_meaning(source, spoken) -> None:
    assert normalize_for_teratts(source).casefold() == f"<ru>{spoken}</ru>".casefold()


@pytest.mark.parametrize("tempo", [0.7, 0.8, 1.0, 1.2, 1.3])
def test_duration_scale_honours_the_entire_supported_tempo_range(tempo) -> None:
    provider = TeraTTSProvider(warmup=False)
    assert provider._duration_scale(TTSRequest(text="Привет", language="ru", voice="ru_f1", tempo=tempo)) == pytest.approx(1/tempo)


@pytest.mark.anyio
async def test_cancelled_synthesis_cannot_overlap_new_inference_or_close() -> None:
    entered, release, overlap = threading.Event(), threading.Event(), threading.Event()

    class BlockingModel(FakeTeraModel):
        active = False

        def generate_speech_stream(self, text, **kwargs):
            if self.active:
                overlap.set()
            self.active = True
            entered.set()
            try:
                assert release.wait(2)
                yield from super().generate_speech_stream(text, **kwargs)
            finally:
                self.active = False

        def close(self):
            if self.active:
                overlap.set()
            super().close()

    model = BlockingModel()
    provider = TeraTTSProvider(model_loader=lambda: model, warmup=False)
    request = TTSRequest(text="Привет.", language="ru", voice="ru_f1")
    first = asyncio.create_task(_collect(provider, request))
    second = closer = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(_collect(provider, request))
        await asyncio.sleep(0.04)
        closer = asyncio.create_task(provider.close())
        await asyncio.sleep(0.04)
        assert not overlap.is_set()
        assert not model.closed
    finally:
        release.set()
        await asyncio.gather(*[task for task in (first, second, closer) if task], return_exceptions=True)
    assert not overlap.is_set()
    assert model.closed


@pytest.mark.anyio
async def test_cancelled_preload_retains_one_model_and_waits_for_warmup() -> None:
    entered, release = threading.Event(), threading.Event()
    model = FakeTeraModel()
    loads = 0

    def loader():
        nonlocal loads
        loads += 1
        entered.set()
        assert release.wait(2)
        return model

    provider = TeraTTSProvider(model_loader=loader, warmup=False)
    first = asyncio.create_task(provider.preload())
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(provider.preload())
        await asyncio.sleep(0.03)
        release.set()
        await second
        assert loads == 1
    finally:
        release.set()
        await asyncio.gather(*[task for task in (first, second) if task], return_exceptions=True)
        await provider.close()


@pytest.mark.anyio
async def test_model_is_not_ready_until_warmup_finishes(monkeypatch) -> None:
    entered, release = threading.Event(), threading.Event()
    provider = TeraTTSProvider(model_loader=FakeTeraModel, warmup=True)

    def warmup():
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(provider, "_warmup_sync", warmup)
    first = asyncio.create_task(provider.preload())
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        second = asyncio.create_task(provider.preload())
        await asyncio.sleep(0.03)
        assert not second.done()
        release.set()
        await asyncio.gather(first, second)
        assert provider.metadata["warm"]
    finally:
        release.set()
        await asyncio.gather(*[t for t in (first, second) if t], return_exceptions=True)
        await provider.close()
