from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import psutil
import soundfile as sf
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    process = psutil.Process()

    load_started = time.perf_counter()
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")
    load_seconds = time.perf_counter() - load_started
    model.prepare_conditionals(str(args.reference), exaggeration=0.5)

    torch.cuda.reset_peak_memory_stats()
    warm_started = time.perf_counter()
    model.generate(
        "Привет. Это короткая проверка голоса.",
        language_id="ru",
        exaggeration=0.5,
        cfg_weight=0.5,
    )
    warmup_seconds = time.perf_counter() - warm_started

    rows: list[dict[str, object]] = []
    for case in cases:
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        wav = model.generate(
            case["text"],
            language_id="ru",
            exaggeration=0.5,
            cfg_weight=0.5,
        )
        synthesis_seconds = time.perf_counter() - started
        audio_np = wav.squeeze().detach().float().cpu().numpy()
        audio_seconds = len(audio_np) / model.sr
        output_path = args.output / f"chatterbox_v3__{case['id']}__clone_baya.wav"
        sf.write(output_path, audio_np, model.sr, subtype="PCM_16")
        rows.append(
            {
                "sample": output_path.name,
                "mode": "voice_clone",
                "text": case["text"],
                "exaggeration": 0.5,
                "cfg_weight": 0.5,
                "synthesis_seconds": round(synthesis_seconds, 4),
                "audio_seconds": round(audio_seconds, 4),
                "rtf": round(synthesis_seconds / audio_seconds, 4),
                "rss_mb_after": round(process.memory_info().rss / 1024**2, 1),
                "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
            }
        )
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    # Official tuning guidance suggests lower CFG and higher exaggeration for
    # a more expressive delivery, so keep one directly comparable variant.
    dialogue = cases[0]
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    wav = model.generate(
        dialogue["text"],
        language_id="ru",
        exaggeration=0.7,
        cfg_weight=0.3,
    )
    synthesis_seconds = time.perf_counter() - started
    audio_np = wav.squeeze().detach().float().cpu().numpy()
    audio_seconds = len(audio_np) / model.sr
    output_path = args.output / "chatterbox_v3__06_expressive__clone_baya.wav"
    sf.write(output_path, audio_np, model.sr, subtype="PCM_16")
    rows.append(
        {
            "sample": output_path.name,
            "mode": "voice_clone_expressive",
            "text": dialogue["text"],
            "exaggeration": 0.7,
            "cfg_weight": 0.3,
            "synthesis_seconds": round(synthesis_seconds, 4),
            "audio_seconds": round(audio_seconds, 4),
            "rtf": round(synthesis_seconds / audio_seconds, 4),
            "rss_mb_after": round(process.memory_info().rss / 1024**2, 1),
            "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
        }
    )
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    manifest = {
        "model": "ResembleAI/chatterbox t3_mtl23ls_v3",
        "runtime": f"torch-{torch.__version__}-cuda-{torch.version.cuda}",
        "gpu": torch.cuda.get_device_name(0),
        "sample_rate": model.sr,
        "load_seconds": round(load_seconds, 4),
        "warmup_seconds": round(warmup_seconds, 4),
        "reference": str(args.reference),
        "samples": rows,
    }
    (args.output / "metrics.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
