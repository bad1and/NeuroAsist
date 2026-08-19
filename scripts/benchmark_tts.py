"""Repeatable TeraTTSv2 benchmark for Russian live-voice phrases."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
import wave
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backend.app.voice.teratts_provider import TeraTTSProvider


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
    "Как-то всё-таки нужно проверить кто-нибудь по-прежнему на связи.",
    "Я плачу за счёт, а ребёнок плачет от радости.",
    "Мука́ закончилась, а мука осталась на столе.",
]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * pct))
    return ordered[index]


def wav_quality_metrics(path: Path) -> dict[str, float | int]:
    with wave.open(str(path), "rb") as audio:
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32)
    if not len(samples):
        return {"rms_dbfs": float("-inf"), "peak_dbfs": float("-inf"), "dc_offset": 0.0, "clipped_samples": 0}
    normalized = samples / 32767.0
    rms = float(np.sqrt(np.mean(np.square(normalized))))
    peak = float(np.max(np.abs(normalized)))
    return {
        "rms_dbfs": 20 * np.log10(max(rms, 1e-12)),
        "peak_dbfs": 20 * np.log10(max(peak, 1e-12)),
        "dc_offset": float(np.mean(normalized)),
        "clipped_samples": int(np.count_nonzero(np.abs(samples) >= 32766)),
    }


async def run(device: str, runs: int, output: Path, model_path: Path | None = None) -> None:
    provider = TeraTTSProvider(device=device, warmup=True, model_path=model_path)
    rows: list[dict] = []
    preload_started = time.perf_counter()
    try:
        await provider.preload()
        model_load_ms = int((time.perf_counter() - preload_started) * 1000)
    except Exception as exc:
        payload = {
            "provider": "teratts",
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
                    result = await provider.synthesize(phrase, "ru_f1", path)
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
                        **wav_quality_metrics(path),
                        "provider": "teratts",
                        "device": provider.metadata["device"],
                        "speaker": "ru_f1",
                        "success": True,
                        "error_type": None,
                    })
                except Exception as exc:
                    rows.append({
                        "provider": "teratts",
                        "device": device,
                        "speaker": "ru_f1",
                        "success": False,
                        "error_type": type(exc).__name__,
                    })
                    print(f"FAIL run={run_index + 1} phrase={index + 1} error={type(exc).__name__}: {exc}")

    good = [row for row in rows if row["success"]]
    failures = len(rows) - len(good)
    summary = {
        "provider": "teratts",
        "device": device,
        "runs": runs,
        "phrases": len(PHRASES),
        "error_rate": failures / len(rows) if rows else 0.0,
        "p50_synthesis_ms": statistics.median(row["synthesis_ms"] for row in good) if good else 0.0,
        "p95_synthesis_ms": percentile([row["synthesis_ms"] for row in good], 0.95),
        "p50_RTF": statistics.median(row["RTF"] for row in good) if good else 0.0,
        "p95_RTF": percentile([row["RTF"] for row in good], 0.95),
        "max_abs_dc_offset": max((abs(float(row["dc_offset"])) for row in good), default=0.0),
        "max_clipped_samples": max((int(row["clipped_samples"]) for row in good), default=0),
        "rows": rows,
    }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"provider=teratts device={device} phrases={len(PHRASES)} runs={runs} error_rate={summary['error_rate']:.1%}")
    print(f"P50 synthesis={summary['p50_synthesis_ms']:.1f}ms P95 synthesis={summary['p95_synthesis_ms']:.1f}ms")
    print(f"P50 RTF={summary['p50_RTF']:.3f} P95 RTF={summary['p95_RTF']:.3f}")
    print(f"json={output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("teratts",), default="teratts")
    parser.add_argument("--device", choices=("cpu", "auto"), default="cpu")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("data/tts_benchmark.json"))
    parser.add_argument("--model-path", type=Path, help="Pinned local snapshot for offline/reproducible runs")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args.device, max(1, args.runs), args.output, args.model_path))
