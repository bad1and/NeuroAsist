"""Compare cleaned Baya with reference-based OpenVoice tone conversion."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
import time
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from apps.backend.app.voice.providers import SileroTTSProvider
from apps.backend.app.voice.style import VoiceStyle


OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Baya-OpenVoice-Comparison"
REFERENCE = ROOT / "data" / "voice-references" / "0718-2-clean.wav"
TEXT = (
    "Привет. Я рядом. Можешь спокойно рассказать, что случилось? "
    "Я всё выслушаю и постараюсь помочь."
)


def install_librosa_compat() -> None:
    """OpenVoice only needs librosa's mel bank here; avoid an old numba pin."""
    if "librosa.filters" in sys.modules:
        return

    def mel(
        sr: int,
        n_fft: int,
        n_mels: int,
        fmin: float = 0.0,
        fmax: float | None = None,
        **_: object,
    ) -> np.ndarray:
        fmax = float(fmax or sr / 2)
        hz_to_mel = lambda hz: 2595.0 * np.log10(1.0 + hz / 700.0)
        mel_to_hz = lambda value: 700.0 * (10.0 ** (value / 2595.0) - 1.0)
        points = mel_to_hz(np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2))
        bins = np.floor((n_fft + 1) * points / sr).astype(int)
        basis = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
        for index in range(n_mels):
            left, center, right = bins[index : index + 3]
            if center > left:
                basis[index, left:center] = np.linspace(0.0, 1.0, center - left, endpoint=False)
            if right > center:
                basis[index, center:right] = np.linspace(1.0, 0.0, right - center, endpoint=False)
        return basis

    filters_module = types.ModuleType("librosa.filters")
    filters_module.mel = mel
    librosa_module = types.ModuleType("librosa")
    librosa_module.filters = filters_module
    sys.modules["librosa"] = librosa_module
    sys.modules["librosa.filters"] = filters_module


async def main_async(device: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not REFERENCE.is_file():
        raise FileNotFoundError(f"Reference audio not found: {REFERENCE}")

    baseline = SileroTTSProvider(
        speaker="baya",
        sample_rate=48000,
        device=device,
        stress_enabled=True,
        audio_postprocessing_enabled=True,
        adaptive_prosody=False,
    )
    converted = SileroTTSProvider(
        speaker="baya",
        sample_rate=48000,
        device=device,
        stress_enabled=True,
        audio_postprocessing_enabled=True,
        adaptive_prosody=False,
        openvoice_enabled=True,
        openvoice_reference_audio_path=REFERENCE,
        openvoice_cache_dir=ROOT / ".cache" / "openvoice-v2",
        openvoice_tau=0.3,
        openvoice_cpu_threads=8,
    )

    started = time.perf_counter()
    await baseline.preload()
    baseline_load_seconds = time.perf_counter() - started
    install_librosa_compat()
    started = time.perf_counter()
    await converted.preload()
    converted_load_seconds = time.perf_counter() - started

    rows: list[dict[str, object]] = []
    for variant_id, label, description, provider in (
        (
            "baya_clean",
            "Baya без конвертации",
            "Чистый Baya с фильтром сипящих верхов; контрольный вариант.",
            baseline,
        ),
        (
            "baya_openvoice",
            "Baya + живой референс",
            "Сохраняем русское произношение Baya, меняем тембр по естественному референсу.",
            converted,
        ),
    ):
        output_path = OUTPUT_DIR / f"{variant_id}.wav"
        started = time.perf_counter()
        result = await provider.synthesize(TEXT, "baya", output_path, VoiceStyle.NORMAL)
        generation_seconds = time.perf_counter() - started
        row = {
            "variant_id": variant_id,
            "label": label,
            "description": description,
            "audio": output_path.name,
            "sample_rate": provider.metadata["sample_rate"],
            "voice_conversion": provider.metadata["voice_conversion"],
            "stress": provider.metadata["stress"],
            "generation_seconds": round(generation_seconds, 4),
            "audio_duration_seconds": round(result.audio_duration_seconds or 0.0, 4),
            "rtf": round(
                generation_seconds / max(result.audio_duration_seconds or 0.0, 1e-6),
                4,
            ),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    manifest = {
        "provider": "silero+openvoice",
        "model": converted.model_name,
        "speaker": "baya",
        "device": converted.metadata["device"],
        "reference": str(REFERENCE),
        "text": TEXT,
        "baseline_load_seconds": round(baseline_load_seconds, 4),
        "converted_load_seconds": round(converted_load_seconds, 4),
        "samples": rows,
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cards = []
    for row in rows:
        cards.append(
            f"<article><h2>{html.escape(str(row['label']))}</h2>"
            f"<p>{html.escape(str(row['description']))}</p>"
            f"<audio controls preload=\"metadata\" src=\"Baya-OpenVoice-Comparison/{html.escape(str(row['audio']))}\"></audio>"
            f"<p class=\"muted\">{row['sample_rate']} Гц · RTF {row['rtf']:.3f}</p></article>"
        )
    page = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Baya OpenVoice comparison</title>
<style>body{{max-width:920px;margin:32px auto;padding:0 20px;background:#17131b;color:#f8eef8;font-family:system-ui,sans-serif}}article{{background:#241c28;border:1px solid #4b3850;border-radius:16px;padding:16px;margin:14px 0}}audio{{width:100%}}p{{line-height:1.5}}.muted{{color:#d3c2d4}}</style></head>
<body><h1>Baya: живость тембра</h1><p>{html.escape(TEXT)}</p><p>Во втором варианте Baya сохраняет произношение и ударения, но тембр преобразуется по живому референсу.</p>{''.join(cards)}</body></html>"""
    page_path = OUTPUT_DIR.parent / "listen_baya_openvoice.html"
    page_path.write_text(page, encoding="utf-8")
    print(f"Listen page: {page_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    args = parser.parse_args()
    asyncio.run(main_async(args.device))


if __name__ == "__main__":
    main()
