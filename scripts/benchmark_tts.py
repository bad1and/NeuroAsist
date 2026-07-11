"""Repeatable Edge/Silero TTS smoke benchmark for Russian live-voice phrases."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import tempfile
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backend.app.voice.providers import EdgeTTSProvider, SileroTTSProvider


PHRASES = [
    "Да.", "Нет, спасибо.", "Как дела?", "Привет! Рад тебя слышать.",
    "Подожди секунду, я сейчас всё проверю.", "Ты уверен, что это правильный ответ?",
    "Сегодня двадцать первое июля две тысячи двадцать шестого года.",
    "Заказ номер 1842 уже готов.", "Открой README и проверь API endpoint.",
    "Python работает, а JavaScript пока загружается.", "Ну блин, опять всё зависло.",
    "Это, честно говоря, довольно странный результат.", "Первый пункт; второй пункт: итог.",
    "Температура минус двенадцать градусов.", "Позвони мне в восемь тридцать.",
    "Можно короче?", "Раз, два, три, четыре, пять.", "Я закончил, всё.",
    "Фраза заканчивается коротким словом да.", "Проверь соединение Wi-Fi, пожалуйста.",
    "Если сеть снова пропадёт, используй локальный голос без дополнительной паузы.",
    "Длинная фраза нужна для проверки того, что окончание не потеряется при нестабильном соединении.",
    "Почему после запятой иногда возникала заметная пауза между соседними аудиосегментами?",
    "Семьдесят пять символов — это цель, а сто десять символов — жёсткий предел.",
    "Скажи по-английски hello world, затем снова продолжай по-русски.",
    "Ни одного потерянного окончания быть не должно.", "Что за хрень происходит с декодером?",
    "Один короткий хвост нужно присоединить к предыдущему сегменту сейчас.",
    "Пять плюс восемь равно тринадцать.", "Готово? Тогда начинаем тест.",
]


async def run(provider_name: str, runs: int) -> None:
    provider = EdgeTTSProvider() if provider_name == "edge_tts" else SileroTTSProvider()
    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as directory:
        for run_index in range(runs):
            for index, phrase in enumerate(PHRASES):
                path = Path(directory) / f"{run_index}-{index}.mp3"
                started = time.perf_counter()
                try:
                    result = await provider.synthesize(phrase, "ru-RU-SvetlanaNeural", path)
                    elapsed = time.perf_counter() - started
                    duration = result.audio_duration_seconds or 0.0
                    rows.append({"ok": True, "ttfb": elapsed, "total": elapsed, "duration": duration,
                                 "rtf": elapsed / duration if duration else 0, "requests": result.chunks_count,
                                 "retries": 0, "adaptive_splits": max(0, result.chunks_count - 1)})
                except Exception as exc:
                    rows.append({"ok": False})
                    print(f"FAIL run={run_index + 1} phrase={index + 1} error={type(exc).__name__}: {exc}")
    good = [row for row in rows if row["ok"]]
    failures = len(rows) - len(good)
    print(f"provider={provider_name} phrases={len(PHRASES)} runs={runs} errors={failures / len(rows):.1%}")
    if good:
        for key in ("ttfb", "total", "duration", "rtf"):
            print(f"{key}: p50={statistics.median(row[key] for row in good):.3f} mean={statistics.mean(row[key] for row in good):.3f}")
        print(f"requests={sum(row['requests'] for row in good)} retries=0 adaptive_splits={sum(row['adaptive_splits'] for row in good)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("edge_tts", "silero"), default="edge_tts")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(run(args.provider, max(1, args.runs)))
