"""Repeatable Silero TTS benchmark for Russian live-voice phrases."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backend.app.voice.providers import SileroTTSProvider


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


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * pct))
    return ordered[index]


async def run(device: str, runs: int, output: Path) -> None:
    provider = SileroTTSProvider(device=device)
    rows: list[dict] = []
    preload_started = time.perf_counter()
    try:
        await provider.preload()
        model_load_ms = int((time.perf_counter() - preload_started) * 1000)
    except Exception as exc:
        payload = {
            "provider": "silero",
            "device": device,
            "success": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        raise

    with tempfile.TemporaryDirectory() as directory:
        for run_index in range(runs):
            for index, phrase in enumerate(PHRASES):
                path = Path(directory) / f"{run_index}-{index}.wav"
                started = time.perf_counter()
                try:
                    result = await provider.synthesize(phrase, "xenia", path)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    audio_ms = (result.audio_duration_seconds or 0.0) * 1000
                    rtf = elapsed_ms / audio_ms if audio_ms else 0.0
                    rows.append({
                        "model_load_ms": model_load_ms if run_index == 0 and index == 0 else 0,
                        "warmup_ms": 0,
                        "synthesis_ms": elapsed_ms,
                        "audio_duration_ms": audio_ms,
                        "RTF": rtf,
                        "inverse_RTF": 1 / rtf if rtf else 0.0,
                        "output_bytes": path.stat().st_size,
                        "provider": "silero",
                        "device": provider.metadata["device"],
                        "speaker": provider.speaker,
                        "success": True,
                        "error_type": None,
                    })
                except Exception as exc:
                    rows.append({
                        "provider": "silero",
                        "device": device,
                        "speaker": provider.speaker,
                        "success": False,
                        "error_type": type(exc).__name__,
                    })
                    print(f"FAIL run={run_index + 1} phrase={index + 1} error={type(exc).__name__}: {exc}")

    good = [row for row in rows if row["success"]]
    failures = len(rows) - len(good)
    summary = {
        "provider": "silero",
        "device": device,
        "runs": runs,
        "phrases": len(PHRASES),
        "error_rate": failures / len(rows) if rows else 0.0,
        "p50_synthesis_ms": statistics.median(row["synthesis_ms"] for row in good) if good else 0.0,
        "p95_synthesis_ms": percentile([row["synthesis_ms"] for row in good], 0.95),
        "p50_RTF": statistics.median(row["RTF"] for row in good) if good else 0.0,
        "p95_RTF": percentile([row["RTF"] for row in good], 0.95),
        "rows": rows,
    }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"provider=silero device={device} phrases={len(PHRASES)} runs={runs} error_rate={summary['error_rate']:.1%}")
    print(f"P50 synthesis={summary['p50_synthesis_ms']:.1f}ms P95 synthesis={summary['p95_synthesis_ms']:.1f}ms")
    print(f"P50 RTF={summary['p50_RTF']:.3f} P95 RTF={summary['p95_RTF']:.3f}")
    print(f"json={output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("silero",), default="silero")
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("data/tts_benchmark.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args.device, max(1, args.runs), args.output))
