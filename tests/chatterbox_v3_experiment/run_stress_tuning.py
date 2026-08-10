"""Isolated Russian-stress experiment for Chatterbox Multilingual V3."""

from __future__ import annotations

import html
import json
import statistics
import sys
import time
from pathlib import Path

from run_experiment import HERE, ROOT, PARAMETER_PROFILES, make_audio_row, sync


OUTPUT = HERE / "output" / "stress-tuning"
REFERENCE = ROOT / "data" / "voice-references" / "qwen-baya-neutral.wav"

PLAIN_GREETING = "Привет! Я рядом и внимательно тебя слушаю."
MARKED_GREETING = "Приве́т! Я ря́дом и внима́тельно тебя́ слу́шаю."
PLAIN_DIALOGUE = (
    "Слушай, я всё проверила. В целом идея рабочая, но есть один неприятный момент: "
    "если запустить это прямо сейчас, мы потеряем часть контекста."
)
MARKED_DIALOGUE = (
    "Слу́шай, я всё прове́рила. В це́лом иде́я рабо́чая, но е́сть оди́н неприя́тный моме́нт: "
    "е́сли запусти́ть э́то пря́мо сейча́с, мы поте́ряем ча́сть ко́нтекста."
)


def build_html(output: Path, rows: list[dict[str, object]], stressed: dict[str, str], report: dict[str, object]) -> None:
    cards = []
    for row in rows:
        cards.append(
            "<article>"
            f"<h2>{html.escape(str(row['label']))}</h2>"
            f"<p class='meta'>{float(row['synthesis_ms']):.0f} ms · "
            f"{float(row['audio_duration_ms']) / 1000:.2f} s · RTF {float(row['rtf']):.3f}</p>"
            f"<p>{html.escape(str(row['text']))}</p>"
            f"<audio controls preload='none' src='{html.escape(str(row['sample']))}'></audio>"
            "</article>"
        )
    stress_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(text)}</td></tr>"
        for name, text in stressed.items()
    )
    page = f"""<!doctype html>
<html lang="ru"><meta charset="utf-8"><title>Chatterbox V3 — Russian stress tuning</title>
<style>
body{{font:16px system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#101216;color:#eee}}
h1{{margin-bottom:5px}} h2{{font-size:17px;margin:0 0 8px}} .meta{{color:#aab0ba}}
.intro{{color:#d8dbe0;line-height:1.5}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px}}
article{{background:#1a1d23;border:1px solid #30343c;border-radius:10px;padding:14px}} article p{{line-height:1.45;color:#c6cad2}} audio{{width:100%}}
table{{border-collapse:collapse;width:100%;margin:16px 0 28px}}td,th{{border:1px solid #30343c;padding:8px;text-align:left;vertical-align:top}}th{{color:#aab0ba}}
</style><body><h1>Chatterbox V3 — Russian stress tuning</h1>
<p class="intro">Один и тот же голос и seed. Слушайте контроль без stress-модуля, затем automatic stress и manual stress. Правильная форма для «привет» — <b>приве́т</b>.</p>
<table><tr><th>Текст</th><th>Что реально уходит в stress-модуль</th></tr>{stress_rows}</table>
<p class="meta">Model load: {float(report['model_load_ms']):.0f} ms · reference: {float(report['reference_prepare_ms']):.0f} ms · median synthesis: {float(report['p50_synthesis_ms']):.0f} ms</p>
<div class="grid">{''.join(cards)}</div></body></html>"""
    (output / "listen.html").write_text(page, encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import psutil
    import torch
    import chatterbox.models.tokenizers.tokenizer as tokenizer_module
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    from russian_text_stresser.text_stresser import RussianTextStresser

    device = "cuda" if torch.cuda.is_available() else "cpu"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    process = psutil.Process()

    stresser = RussianTextStresser()
    stressed = {
        "greeting_plain": stresser.stress_text(PLAIN_GREETING),
        "greeting_marked": stresser.stress_text(MARKED_GREETING),
        "dialogue_plain": stresser.stress_text(PLAIN_DIALOGUE),
        "dialogue_marked": stresser.stress_text(MARKED_DIALOGUE),
    }

    load_started = time.perf_counter()
    model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
    sync(device)
    model_load_ms = (time.perf_counter() - load_started) * 1000

    reference_started = time.perf_counter()
    model.prepare_conditionals(str(REFERENCE), exaggeration=0.5)
    sync(device)
    reference_prepare_ms = (time.perf_counter() - reference_started) * 1000

    original_add_stress = tokenizer_module.add_russian_stress
    rows: list[dict[str, object]] = []
    jobs = [
        ("greeting", "control_no_stress", PLAIN_GREETING, "Контроль: без stress-модуля", False),
        ("greeting", "auto_stress", PLAIN_GREETING, "Автоматические русские ударения", True),
        ("greeting", "manual_stress", MARKED_GREETING, "Явно заданные ударения", True),
        ("dialogue", "auto_stress", PLAIN_DIALOGUE, "Диалог: автоматические ударения", True),
        ("dialogue", "manual_stress", MARKED_DIALOGUE, "Диалог: явно заданные ударения", True),
    ]
    profile = PARAMETER_PROFILES["baseline"]
    try:
        for index, (case_id, mode, text, label, use_stresser) in enumerate(jobs, start=1):
            tokenizer_module.add_russian_stress = original_add_stress if use_stresser else (lambda value: value)
            output_path = OUTPUT / f"{case_id}__{mode}.wav"
            row = make_audio_row(
                model=model,
                torch=torch,
                psutil=psutil,
                process=process,
                text=text,
                output_path=output_path,
                profile_name="baseline",
                profile=profile,
                case_id=case_id,
                label=label,
                seed=20260806 + index,
                device=device,
            )
            row["mode"] = mode
            row["stress_enabled"] = use_stresser
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        tokenizer_module.add_russian_stress = original_add_stress

    report = {
        "model": "ResembleAI/chatterbox t3_mtl23ls_v3",
        "device": device,
        "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
        "sample_rate": model.sr,
        "reference": str(REFERENCE),
        "model_load_ms": round(model_load_ms, 1),
        "reference_prepare_ms": round(reference_prepare_ms, 1),
        "p50_synthesis_ms": round(statistics.median(float(row["synthesis_ms"]) for row in rows), 1),
        "rows": rows,
        "stressed_text": stressed,
    }
    (OUTPUT / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT / "STRESS.md").write_text(
        "# Russian stress tuning\n\n"
        "Причина исходной ошибки: в первом прогоне отсутствовал `russian-text-stresser`, "
        "поэтому Chatterbox пропускал русскую разметку ударений. В этом изолированном окружении "
        "пакет установлен, а `listen.html` содержит контроль, автоматическую и ручную разметку.\n\n"
        "Ожидаемая форма: `приве́т`, ударение на второй слог. Если автоматический вариант звучит "
        "нестабильно на конкретной реплике, перед TTS можно передавать вариант с combining acute "
        "(`е́`) для критичных слов.\n",
        encoding="utf-8",
    )
    build_html(OUTPUT, rows, stressed, report)
    print(f"report={OUTPUT / 'metrics.json'}", flush=True)
    print(f"listen={OUTPUT / 'listen.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
