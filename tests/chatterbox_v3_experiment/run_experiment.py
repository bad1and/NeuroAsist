"""Isolated Chatterbox Multilingual V3 listening and latency experiment.

This file intentionally lives under tests/ and does not import the production
voice service. It writes all generated artifacts beside this script.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import statistics
import sys
import time
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "cases.json"
DEFAULT_REFERENCE = ROOT / "data" / "voice-references" / "qwen-baya-neutral.wav"
DEFAULT_OUTPUT = HERE / "output"

PARAMETER_PROFILES = {
    "baseline": {
        "label": "База: 0.5 / 0.5",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "temperature": 0.8,
        "repetition_penalty": 2.0,
        "min_p": 0.05,
        "top_p": 1.0,
    },
    "calm": {
        "label": "Спокойный: 0.3 / 0.7",
        "exaggeration": 0.3,
        "cfg_weight": 0.7,
        "temperature": 0.7,
        "repetition_penalty": 2.0,
        "min_p": 0.05,
        "top_p": 0.95,
    },
    "expressive": {
        "label": "Выразительный: 0.7 / 0.3",
        "exaggeration": 0.7,
        "cfg_weight": 0.3,
        "temperature": 0.8,
        "repetition_penalty": 2.0,
        "min_p": 0.05,
        "top_p": 1.0,
    },
    "stable": {
        "label": "Стабильный sampling",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "temperature": 0.65,
        "repetition_penalty": 2.2,
        "min_p": 0.08,
        "top_p": 0.92,
    },
}


def sync(device: str) -> None:
    if device == "cuda":
        import torch

        torch.cuda.synchronize()


def audio_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def write_wav(path: Path, waveform, sample_rate: int) -> None:
    import soundfile as sf

    audio = waveform.squeeze().detach().float().cpu().numpy()
    sf.write(path, audio, sample_rate, subtype="PCM_16")


def make_audio_row(
    *,
    model,
    torch,
    psutil,
    process,
    text: str,
    output_path: Path,
    profile_name: str,
    profile: dict[str, object],
    case_id: str,
    label: str,
    seed: int,
    device: str,
    chunk_index: int | None = None,
) -> dict[str, object]:
    torch.manual_seed(seed)
    if device == "cuda":
        torch.cuda.manual_seed_all(seed)
        torch.cuda.reset_peak_memory_stats()
    sync(device)
    started = time.perf_counter()
    waveform = model.generate(
        text,
        language_id="ru",
        exaggeration=profile["exaggeration"],
        cfg_weight=profile["cfg_weight"],
        temperature=profile["temperature"],
        repetition_penalty=profile["repetition_penalty"],
        min_p=profile["min_p"],
        top_p=profile["top_p"],
    )
    sync(device)
    synthesis_seconds = time.perf_counter() - started
    write_wav(output_path, waveform, model.sr)
    duration = audio_duration(output_path)
    peak_vram = 0.0
    if device == "cuda":
        peak_vram = torch.cuda.max_memory_allocated() / 1024**2
    return {
        "sample": output_path.name,
        "case_id": case_id,
        "label": label,
        "text": text,
        "profile": profile_name,
        "profile_label": profile["label"],
        "seed": seed,
        "chunk_index": chunk_index,
        "synthesis_ms": round(synthesis_seconds * 1000, 1),
        "audio_duration_ms": round(duration * 1000, 1),
        "rtf": round(synthesis_seconds / duration, 4) if duration else None,
        "rss_mb_after": round(process.memory_info().rss / 1024**2, 1),
        "peak_vram_mb": round(peak_vram, 1),
        "parameters": {
            key: value for key, value in profile.items() if key != "label"
        },
    }


def concatenate_wavs(paths: list[Path], output_path: Path, pause_ms: int = 100) -> None:
    import soundfile as sf
    import numpy as np

    chunks = []
    sample_rate = None
    for path in paths:
        audio, rate = sf.read(path, dtype="float32")
        if sample_rate is None:
            sample_rate = rate
        if rate != sample_rate:
            raise RuntimeError("Chunk WAV files have different sample rates")
        chunks.append(audio)
    if not chunks or sample_rate is None:
        raise RuntimeError("No WAV chunks to concatenate")
    channels = 1 if chunks[0].ndim == 1 else chunks[0].shape[1]
    silence = np.zeros((round(sample_rate * pause_ms / 1000), channels), dtype="float32")
    normalized = [chunk[:, None] if chunk.ndim == 1 else chunk for chunk in chunks]
    joined = np.concatenate(
        [part for index, chunk in enumerate(normalized) for part in (([chunk, silence] if index < len(normalized) - 1 else [chunk]))],
        axis=0,
    )
    sf.write(output_path, joined[:, 0] if channels == 1 else joined, sample_rate, subtype="PCM_16")


def build_listen_html(output: Path, rows: list[dict[str, object]], summary: dict[str, object]) -> None:
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault(str(row["case_id"]), []).append(row)
    sections = []
    for case_id, group in groups.items():
        first = group[0]
        cards = []
        for row in group:
            cards.append(
                "<article>"
                f"<h3>{html.escape(str(row['profile_label']))}</h3>"
                f"<p class='meta'>{float(row['synthesis_ms']):.0f} ms · {float(row['audio_duration_ms']) / 1000:.2f} s · RTF {float(row['rtf']):.3f}</p>"
                f"<audio controls preload='none' src='{html.escape(str(row['sample']))}'></audio>"
                "</article>"
            )
        sections.append(
            f"<section><h2>{html.escape(case_id)} — {html.escape(str(first['label']))}</h2>"
            f"<p class='text'>{html.escape(str(first['text']))}</p><div class='grid'>{''.join(cards)}</div></section>"
        )
    page = f"""<!doctype html>
<html lang="ru"><meta charset="utf-8"><title>Chatterbox V3 — эксперимент</title>
<style>
body{{font:16px system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#101216;color:#eee}}
h1{{margin-bottom:4px}} h2{{margin-bottom:8px}} h3{{font-size:17px;margin:0 0 8px}}
.muted,.meta{{color:#aab0ba}} .text{{max-width:900px;line-height:1.5;color:#d8dbe0}}
section{{padding:22px 0;border-top:1px solid #30343c}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}}
article{{background:#1a1d23;border:1px solid #30343c;border-radius:10px;padding:14px}} audio{{width:100%}}
table{{border-collapse:collapse;margin:18px 0 28px;width:100%}} td,th{{border:1px solid #30343c;padding:8px;text-align:left}} th{{color:#aab0ba}}
</style><body>
<h1>Chatterbox Multilingual V3</h1>
<p class="muted">Изолированный прогон. Сначала слушайте одну и ту же фразу в разных профилях, затем сравнивайте raw/normalized numbers и long-form.</p>
<table><tr><th>Показатель</th><th>Значение</th></tr>
<tr><td>Device</td><td>{html.escape(str(summary['device']))}</td></tr>
<tr><td>Model load</td><td>{float(summary['model_load_ms']):.0f} ms</td></tr>
<tr><td>Warm-up</td><td>{float(summary['warmup_ms']):.0f} ms</td></tr>
<tr><td>Median synthesis</td><td>{float(summary['p50_synthesis_ms']):.0f} ms</td></tr>
<tr><td>P95 synthesis</td><td>{float(summary['p95_synthesis_ms']):.0f} ms</td></tr>
<tr><td>Median RTF</td><td>{float(summary['p50_rtf']):.3f}</td></tr></table>
{''.join(sections)}
</body></html>"""
    (output / "listen.html").write_text(page, encoding="utf-8")


def write_results_md(output: Path, report: dict[str, object]) -> None:
    rows = report["rows"]
    lines = [
        "# Chatterbox Multilingual V3 — результаты",
        "",
        "Это изолированный эксперимент под `tests/chatterbox_v3_experiment`; production-код не используется.",
        "",
        f"- Устройство: **{report['device']}**",
        f"- Загрузка модели: **{report['model_load_ms']:.0f} мс**",
        f"- Подготовка voice reference: **{report['conditionals_ms']:.0f} мс**",
        f"- Warm-up: **{report['warmup_ms']:.0f} мс**",
        f"- Медианная генерация: **{report['p50_synthesis_ms']:.0f} мс**",
        f"- P95 генерации: **{report['p95_synthesis_ms']:.0f} мс**",
        f"- Медианный RTF: **{report['p50_rtf']:.3f}** (меньше 1 — быстрее реального времени)",
        "",
        "Откройте `listen.html` и слушайте профили рядом. У Multilingual V3 API не отдаёт аудио потоково: измеренная генерация — это задержка до полного WAV. Разбиение на chunks уменьшает задержку до первой готовой фразы, но обычно увеличивает суммарное время.",
        "",
        "| Sample | Профиль | Генерация, мс | Аудио, с | RTF |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['sample']}` | {row['profile_label']} | {float(row['synthesis_ms']):.0f} | {float(row['audio_duration_ms']) / 1000:.2f} | {float(row['rtf']):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Что слушать",
            "",
            "1. `02_dialogue`: baseline / calm / expressive / stable — характер и артефакты.",
            "2. `04_numbers_raw` и `05_numbers_normalized` — критичная для ассистента разница.",
            "3. `06_long_form`: baseline — стабильность длинной мысли.",
            "4. `chunked_long_form`: оценка задержки первой фразы при разбиении текста.",
        ]
    )
    (output / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--profiles", nargs="+", choices=tuple(PARAMETER_PROFILES), default=("baseline", "calm", "expressive", "stable"))
    parser.add_argument("--quick", action="store_true", help="Only baseline + parameter sweep on the dialogue sample")
    args = parser.parse_args()

    import psutil
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    if args.device == "auto" and not torch.cuda.is_available():
        device = "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in cases}
    args.output.mkdir(parents=True, exist_ok=True)
    process = psutil.Process(os.getpid())

    load_started = time.perf_counter()
    model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
    sync(device)
    model_load_ms = (time.perf_counter() - load_started) * 1000

    cond_started = time.perf_counter()
    model.prepare_conditionals(str(args.reference), exaggeration=0.5)
    sync(device)
    conditionals_ms = (time.perf_counter() - cond_started) * 1000

    warm_started = time.perf_counter()
    warm_profile = PARAMETER_PROFILES["baseline"]
    warm_path = args.output / "_warmup.wav"
    make_audio_row(
        model=model, torch=torch, psutil=psutil, process=process,
        text="Привет. Это короткая проверка голоса.", output_path=warm_path,
        profile_name="warmup", profile=warm_profile, case_id="warmup", label="Warm-up",
        seed=20260806, device=device,
    )
    warmup_ms = (time.perf_counter() - warm_started) * 1000
    warm_path.unlink(missing_ok=True)

    rows: list[dict[str, object]] = []

    def render(case_id: str, profile_name: str, suffix: str = "", seed_offset: int = 0) -> dict[str, object]:
        case = by_id[case_id]
        profile = PARAMETER_PROFILES[profile_name]
        filename = f"{case_id}__{profile_name}{suffix}.wav"
        row = make_audio_row(
            model=model, torch=torch, psutil=psutil, process=process,
            text=case["text"], output_path=args.output / filename,
            profile_name=profile_name, profile=profile, case_id=case_id,
            label=case["label"], seed=20260806 + seed_offset, device=device,
        )
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return row

    if args.quick:
        render("02_dialogue", "baseline", seed_offset=1)
        for index, profile_name in enumerate(args.profiles):
            if profile_name != "baseline":
                render("02_dialogue", profile_name, seed_offset=10 + index)
    else:
        for index, case in enumerate(cases):
            render(case["id"], "baseline", seed_offset=index + 1)
        for index, profile_name in enumerate(args.profiles):
            if profile_name != "baseline":
                render("02_dialogue", profile_name, seed_offset=100 + index)
                render("03_emotion", profile_name, seed_offset=200 + index)

        # A separate first-ready-chunk experiment. The model itself is not
        # streaming; this simulates the application-level split strategy.
        long_case = by_id["06_long_form"]
        chunks = [
            "Иногда хорошая система отличается от посредственной не количеством функций, а тем, насколько естественно она ведёт себя в мелочах.",
            "Она не перебивает, не торопится отвечать и не превращает каждую реплику в длинную лекцию.",
            "Когда нужно — говорит коротко. Когда ситуация сложная — объясняет подробнее, сохраняя мысль, интонацию и нормальный человеческий ритм.",
        ]
        chunk_rows = []
        chunk_paths = []
        for index, chunk in enumerate(chunks, start=1):
            profile = PARAMETER_PROFILES["baseline"]
            path = args.output / f"06_long_form__chunk_{index:02d}.wav"
            row = make_audio_row(
                model=model, torch=torch, psutil=psutil, process=process,
                text=chunk, output_path=path, profile_name="baseline",
                profile=profile, case_id="chunked_long_form", label="Long form — chunked",
                seed=20261000 + index, device=device, chunk_index=index,
            )
            chunk_rows.append(row)
            chunk_paths.append(path)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        combined_path = args.output / "chunked_long_form__baseline.wav"
        concatenate_wavs(chunk_paths, combined_path)
        combined_duration = audio_duration(combined_path)
        total_ms = sum(float(item["synthesis_ms"]) for item in chunk_rows)
        rows.append({
            "sample": combined_path.name,
            "case_id": "chunked_long_form",
            "label": "Long form — chunked",
            "text": " ".join(chunks),
            "profile": "baseline",
            "profile_label": "База: chunked",
            "seed": None,
            "chunk_index": None,
            "synthesis_ms": round(total_ms, 1),
            "audio_duration_ms": round(combined_duration * 1000, 1),
            "rtf": round(total_ms / 1000 / combined_duration, 4),
            "first_chunk_ms": chunk_rows[0]["synthesis_ms"],
            "chunks": chunk_rows,
            "parameters": {key: value for key, value in PARAMETER_PROFILES["baseline"].items() if key != "label"},
        })
        for path in chunk_paths:
            path.unlink(missing_ok=True)

    good = [row for row in rows if row.get("rtf") is not None]
    report = {
        "model": "ResembleAI/chatterbox t3_mtl23ls_v3",
        "runtime": f"torch-{torch.__version__}-cuda-{torch.version.cuda}",
        "device": device,
        "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
        "sample_rate": model.sr,
        "reference": str(args.reference),
        "model_load_ms": round(model_load_ms, 1),
        "conditionals_ms": round(conditionals_ms, 1),
        "warmup_ms": round(warmup_ms, 1),
        "p50_synthesis_ms": round(statistics.median(float(row["synthesis_ms"]) for row in good), 1),
        "p95_synthesis_ms": round(percentile([float(row["synthesis_ms"]) for row in good], 0.95), 1),
        "p50_rtf": round(statistics.median(float(row["rtf"]) for row in good), 4),
        "p95_rtf": round(percentile([float(row["rtf"]) for row in good], 0.95), 4),
        "rows": rows,
    }
    (args.output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    build_listen_html(args.output, rows, report)
    write_results_md(args.output, report)
    print(f"report={args.output / 'metrics.json'}", flush=True)
    print(f"listen={args.output / 'listen.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
