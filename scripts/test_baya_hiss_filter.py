"""Create gentle low-pass variants of the Baya artifact sample."""

from __future__ import annotations

import html
import json
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "tts-model-comparison" / "Baya-Artifact-Comparison"
SOURCE = OUTPUT_DIR / "baya_current_48k.wav"


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise RuntimeError("Expected mono PCM16 WAV")
        return (
            np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(np.float32) / 32768.0,
            audio.getframerate(),
        )


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes((clipped * 32767.0).astype("<i2").tobytes())


def main() -> None:
    samples, sample_rate = read_wav(SOURCE)
    variants = [
        ("lowpass_12k", "Мягкий фильтр до 12 кГц", 12000),
        ("lowpass_10k", "Более сильный фильтр до 10 кГц", 10000),
    ]
    rows = []
    for variant_id, label, cutoff_hz in variants:
        sos = butter(4, cutoff_hz / (sample_rate / 2), btype="lowpass", output="sos")
        filtered = sosfiltfilt(sos, samples).astype(np.float32)
        output_path = OUTPUT_DIR / f"baya_{variant_id}.wav"
        write_wav(output_path, filtered, sample_rate)
        rows.append({
            "variant_id": variant_id,
            "label": label,
            "audio": output_path.name,
            "cutoff_hz": cutoff_hz,
        })

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"].extend(rows)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cards = []
    for row in rows:
        cards.append(
            f"<article><h2>{html.escape(row['label'])}</h2>"
            f"<p>Исходник: текущий вариант 48 кГц.</p>"
            f"<audio controls preload=\"metadata\" src=\"Baya-Artifact-Comparison/{html.escape(row['audio'])}\"></audio></article>"
        )
    page_path = OUTPUT_DIR.parent / "listen_baya_artifacts.html"
    page = page_path.read_text(encoding="utf-8")
    page = page.replace("</body></html>", "".join(cards) + "</body></html>")
    page_path.write_text(page, encoding="utf-8")
    print(f"Created {len(rows)} filtered variants in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
