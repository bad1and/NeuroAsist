"""Isolated JSON-lines worker for the optional Qwen3-TTS quality gate.

Install Qwen and CUDA PyTorch in a separate virtual environment. The main
backend never imports this module or its dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path


def _write_wav(path: Path, waveform, sample_rate: int) -> None:
    import numpy as np

    samples = np.asarray(waveform, dtype=np.float32).reshape(-1)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(temporary), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--reference-wav", type=Path, required=True)
    parser.add_argument("--reference-text", required=True)
    args = parser.parse_args()

    import torch
    from qwen_tts import Qwen3TTSModel

    if not torch.cuda.is_available():
        raise RuntimeError("Qwen quality worker requires CUDA")
    torch.cuda.reset_peak_memory_stats()
    model = Qwen3TTSModel.from_pretrained(
        args.model,
        revision=args.revision,
        device_map="cuda:0",
        dtype=torch.float16,
        attn_implementation="sdpa",
    )
    voice_prompt = model.create_voice_clone_prompt(
        ref_audio=str(args.reference_wav.resolve()),
        ref_text=args.reference_text,
        x_vector_only_mode=False,
    )
    print(
        json.dumps(
            {
                "type": "ready",
                "model": args.model,
                "revision": args.revision,
                "peak_vram_gb": torch.cuda.max_memory_allocated() / (1024**3),
            }
        ),
        flush=True,
    )

    for line in sys.stdin:
        request = json.loads(line)
        request_id = str(request.get("id", ""))
        started = time.perf_counter()
        try:
            last_error: Exception | None = None
            for attempt in (1, 2):
                try:
                    wavs, sample_rate = model.generate_voice_clone(
                        text=str(request["text"]),
                        language=str(request.get("language", "Russian")),
                        voice_clone_prompt=voice_prompt,
                    )
                    output_path = Path(request["output_path"])
                    _write_wav(output_path, wavs[0], int(sample_rate))
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt == 2:
                        raise
                    torch.cuda.empty_cache()
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            print(
                json.dumps(
                    {
                        "type": "result",
                        "id": request_id,
                        "ok": True,
                        "output_path": str(output_path),
                        "synthesis_ms": elapsed_ms,
                        "attempts": attempt,
                        "peak_vram_gb": torch.cuda.max_memory_allocated() / (1024**3),
                    }
                ),
                flush=True,
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "type": "result",
                        "id": request_id,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "peak_vram_gb": torch.cuda.max_memory_allocated() / (1024**3),
                    }
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
