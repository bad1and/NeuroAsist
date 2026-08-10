"""Build a small local listening page for the Qwen3-TTS reference benchmark."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    analysis = json.loads((args.root / "analysis.json").read_text(encoding="utf-8"))
    metrics = {
        item["reference"] + "___" + item["case_id"]: item
        for item in json.loads((args.root / "metrics.json").read_text(encoding="utf-8"))
    }
    groups: dict[str, list[dict[str, object]]] = {}
    for item in analysis:
        groups.setdefault(str(item["case_id"]), []).append(item)
    sections = []
    for case_id, rows in groups.items():
        first = rows[0]
        cards = []
        for row in rows:
            metric = metrics.get(str(row["reference"] + "___" + case_id), {})
            cards.append(
                "<article>"
                f"<h3>{html.escape(str(row['reference']))}</h3>"
                f"<p class='meta'>audio {float(row['duration_seconds']):.2f}s · "
                f"wall {float(metric.get('wall_s', 0)):.2f}s · "
                f"RTF {float(metric.get('rtf', 0)):.3f} · WER {float(row['wer']):.3f}</p>"
                f"<p class='transcript'>{html.escape(str(row['transcript']))}</p>"
                f"<audio controls preload='none' src='{html.escape(str(row['file']))}'></audio>"
                "</article>"
            )
        sections.append(
            f"<section><h2>{html.escape(case_id)}</h2>"
            f"<p class='text'>{html.escape(str(first['text']))}</p>"
            f"<div class='grid'>{''.join(cards)}</div></section>"
        )
    page = f"""<!doctype html>
<html lang="ru"><meta charset="utf-8"><title>Qwen3-TTS reference benchmark</title>
<style>
body{{font:16px system-ui,sans-serif;max-width:1180px;margin:32px auto;padding:0 20px;background:#101216;color:#eee}}
h1{{margin-bottom:4px}} h2{{margin-bottom:8px}} h3{{margin:0 0 8px;text-transform:capitalize}}
.meta{{color:#aab0ba;font-size:14px}} .text,.transcript{{max-width:920px;line-height:1.5;color:#d8dbe0}}
section{{padding:22px 0;border-top:1px solid #30343c}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px}}
article{{background:#1a1d23;border:1px solid #30343c;border-radius:10px;padding:14px}} audio{{width:100%}}
</style><body><h1>Qwen3-TTS — сравнение voice references</h1>
<p class="meta">Q4_K_M + Q8 mmproj, llama.cpp Vulkan mainline, seed 12345. Сначала сравнивайте clean и short внутри одного теста.</p>
{''.join(sections)}</body></html>"""
    (args.root / "listen.html").write_text(page, encoding="utf-8")
    print(args.root / "listen.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
