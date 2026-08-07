"""Small isolated quality-tuning pack for Chatterbox Multilingual V3."""

from __future__ import annotations

import argparse
import html
import json
import statistics
import sys
import time
from pathlib import Path

from run_experiment import (
    HERE,
    PARAMETER_PROFILES,
    ROOT,
    audio_duration,
    make_audio_row,
    sync,
)


OUTPUT = HERE / "output" / "quality-tuning"
REFERENCES = {
    "qwen_baya": ROOT / "data" / "voice-references" / "qwen-baya-neutral.wav",
    "clean_0718_10s": ROOT / "data" / "voice-references" / "0718-2-clean.wav",
    "clean_0718_5s": ROOT / "data" / "voice-references" / "0718-2-reference-5s.wav",
}
CASES = {
    "greeting": "Привет! Я рядом и внимательно тебя слушаю.",
    "dialogue": "Слушай, я всё проверила. В целом идея рабочая, но есть один неприятный момент: если запустить это прямо сейчас, мы потеряем часть контекста. Давай сначала сохраним состояние, а потом спокойно продолжим.",
    "numbers": "Проверка завершена пятого августа две тысячи двадцать шестого года в двадцать один час сорок пять минут. Видеокарта джи ти икс одна тысяча шестьсот шестьдесят супер имеет шесть гигабайт видеопамяти; эй пи ай ответил за сто восемьдесят семь миллисекунд, а версия приложения — ноль точка пять точка три.",
}
QUALITY_PROFILES = {
    "baseline": PARAMETER_PROFILES["baseline"],
    "stable": PARAMETER_PROFILES["stable"],
    "expressive": PARAMETER_PROFILES["expressive"],
    "cfg0": {
        "label": "CFG 0: без привязки к языку reference",
        "exaggeration": 0.5,
        "cfg_weight": 0.0,
        "temperature": 0.8,
        "repetition_penalty": 2.0,
        "min_p": 0.05,
        "top_p": 1.0,
    },
}


def build_html(output: Path, rows: list[dict[str, object]], summary: dict[str, object]) -> None:
    cards = []
    for row in rows:
        cards.append(
            "<article>"
            f"<h2>{html.escape(str(row['reference_label']))}</h2>"
            f"<h3>{html.escape(str(row['case_id']))} · {html.escape(str(row['profile_label']))}</h3>"
            f"<p class='meta'>{float(row['synthesis_ms']):.0f} ms · {float(row['audio_duration_ms']) / 1000:.2f} s · RTF {float(row['rtf']):.3f}</p>"
            f"<p>{html.escape(str(row['text']))}</p>"
            f"<audio controls preload='none' src='{html.escape(str(row['sample']))}'></audio>"
            "</article>"
        )
    page = f"""<!doctype html>
<html lang="ru"><meta charset="utf-8"><title>Chatterbox V3 — quality tuning</title>
<style>
body{{font:16px system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#101216;color:#eee}}
h1{{margin-bottom:4px}} h2{{font-size:18px;margin:0 0 5px}} h3{{font-size:16px;color:#d8dbe0;margin:0 0 8px}}
.meta{{color:#aab0ba}} .intro{{color:#d8dbe0;line-height:1.5}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px}}
article{{background:#1a1d23;border:1px solid #30343c;border-radius:10px;padding:14px}} article p{{line-height:1.45;color:#c6cad2}} audio{{width:100%}}
</style><body><h1>Chatterbox V3 — quality tuning</h1>
<p class="intro">Сравнивайте сначала один и тот же dialogue между reference/profile, затем numbers. Главный вопрос — чистота, похожесть голоса, ударения, артефакты и естественность пауз.</p>
<p class="meta">Reference preparation: {float(summary['reference_prepare_ms']):.0f} ms суммарно · median synthesis: {float(summary['p50_synthesis_ms']):.0f} ms</p>
<div class="grid">{''.join(cards)}</div></body></html>"""
    (output / "listen.html").write_text(page, encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    import psutil
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    args.output.mkdir(parents=True, exist_ok=True)
    process = psutil.Process()

    load_started = time.perf_counter()
    model = ChatterboxMultilingualTTS.from_pretrained(device=args.device, t3_model="v3")
    sync(args.device)
    model_load_ms = (time.perf_counter() - load_started) * 1000

    # The same dialogue is used for reference/profile comparisons.
    jobs = [
        ("qwen_baya", "dialogue", "baseline"),
        ("qwen_baya", "dialogue", "stable"),
        ("qwen_baya", "dialogue", "expressive"),
        ("qwen_baya", "dialogue", "cfg0"),
        ("clean_0718_10s", "dialogue", "baseline"),
        ("clean_0718_5s", "dialogue", "baseline"),
        ("clean_0718_10s", "greeting", "baseline"),
        ("clean_0718_5s", "greeting", "baseline"),
        ("qwen_baya", "numbers", "baseline"),
        ("clean_0718_10s", "numbers", "baseline"),
    ]
    rows: list[dict[str, object]] = []
    reference_prepare_ms = 0.0
    prepared_reference = None
    for index, (reference_name, case_id, profile_name) in enumerate(jobs, start=1):
        if reference_name != prepared_reference:
            started = time.perf_counter()
            model.prepare_conditionals(str(REFERENCES[reference_name]), exaggeration=0.5)
            sync(args.device)
            reference_prepare_ms += (time.perf_counter() - started) * 1000
            prepared_reference = reference_name
        profile = QUALITY_PROFILES[profile_name]
        output_path = args.output / f"{reference_name}__{case_id}__{profile_name}.wav"
        row = make_audio_row(
            model=model,
            torch=torch,
            psutil=psutil,
            process=process,
            text=CASES[case_id],
            output_path=output_path,
            profile_name=profile_name,
            profile=profile,
            case_id=case_id,
            label=case_id,
            seed=20262000 + index,
            device=args.device,
        )
        row["reference"] = reference_name
        row["reference_label"] = {
            "qwen_baya": "Qwen Baya reference 7.65 s",
            "clean_0718_10s": "0718 clean reference 10.85 s",
            "clean_0718_5s": "0718 reference 5.40 s",
        }[reference_name]
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    report = {
        "model": "ResembleAI/chatterbox t3_mtl23ls_v3",
        "device": args.device,
        "gpu": torch.cuda.get_device_name(0) if args.device == "cuda" else None,
        "sample_rate": model.sr,
        "model_load_ms": round(model_load_ms, 1),
        "reference_prepare_ms": round(reference_prepare_ms, 1),
        "p50_synthesis_ms": round(statistics.median(float(row["synthesis_ms"]) for row in rows), 1),
        "rows": rows,
    }
    (args.output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    build_html(args.output, rows, report)
    print(f"listen={args.output / 'listen.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
