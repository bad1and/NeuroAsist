from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import psutil
import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--reference-text")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    if not args.reference_text:
        metadata = json.loads(args.reference.with_suffix(".json").read_text(encoding="utf-8"))
        args.reference_text = metadata["text"]
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    process = psutil.Process()

    load_started = time.perf_counter()
    model = OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16
    )
    load_seconds = time.perf_counter() - load_started
    torch.cuda.reset_peak_memory_stats()
    clone_prompt = model.create_voice_clone_prompt(
        ref_audio=str(args.reference), ref_text=args.reference_text
    )

    # One discarded warm-up catches first-call kernel/setup cost.
    warm_started = time.perf_counter()
    model.generate(
        text="Привет. Это короткая проверка голоса.",
        language="ru",
        voice_clone_prompt=clone_prompt,
        num_step=32,
    )
    warmup_seconds = time.perf_counter() - warm_started

    rows: list[dict[str, object]] = []
    for case in cases:
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        audio = model.generate(
            text=case["text"],
            language="ru",
            voice_clone_prompt=clone_prompt,
            num_step=32,
        )[0]
        synthesis_seconds = time.perf_counter() - started
        audio_np = np.asarray(audio, dtype=np.float32).squeeze()
        audio_seconds = len(audio_np) / 24000
        output_path = args.output / f"omnivoice__{case['id']}__clone_baya.wav"
        sf.write(output_path, audio_np, 24000, subtype="PCM_16")
        rows.append(
            {
                "sample": output_path.name,
                "mode": "voice_clone",
                "text": case["text"],
                "synthesis_seconds": round(synthesis_seconds, 4),
                "audio_seconds": round(audio_seconds, 4),
                "rtf": round(synthesis_seconds / audio_seconds, 4),
                "rss_mb_after": round(process.memory_info().rss / 1024**2, 1),
                "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
            }
        )
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    dialogue = cases[0]
    for suffix, instruction in (
        ("warm", "female, young adult, Russian accent, warm, calm, medium pitch"),
        ("expressive", "female, young adult, Russian accent, lively, expressive, medium pitch"),
    ):
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        audio = model.generate(
            text=dialogue["text"], language="ru", instruct=instruction, num_step=32
        )[0]
        synthesis_seconds = time.perf_counter() - started
        audio_np = np.asarray(audio, dtype=np.float32).squeeze()
        audio_seconds = len(audio_np) / 24000
        output_path = args.output / f"omnivoice__06_design_{suffix}.wav"
        sf.write(output_path, audio_np, 24000, subtype="PCM_16")
        rows.append(
            {
                "sample": output_path.name,
                "mode": "voice_design",
                "instruction": instruction,
                "text": dialogue["text"],
                "synthesis_seconds": round(synthesis_seconds, 4),
                "audio_seconds": round(audio_seconds, 4),
                "rtf": round(synthesis_seconds / audio_seconds, 4),
                "rss_mb_after": round(process.memory_info().rss / 1024**2, 1),
                "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
            }
        )
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    manifest = {
        "model": "k2-fsa/OmniVoice",
        "runtime": f"torch-{torch.__version__}-cuda-{torch.version.cuda}",
        "gpu": torch.cuda.get_device_name(0),
        "sample_rate": 24000,
        "dtype": "float16",
        "load_seconds": round(load_seconds, 4),
        "warmup_seconds": round(warmup_seconds, 4),
        "reference": str(args.reference),
        "reference_text": args.reference_text,
        "samples": rows,
    }
    (args.output / "metrics.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
