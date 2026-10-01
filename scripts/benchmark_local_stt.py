"""Compare local ASR engines without changing Iris or uploading recordings.

Optional engines may be installed into an isolated --site-packages directory.
Input: a JSON list of {audio, reference, tags} rows. Paths are relative to the
manifest. Streaming timing uses a virtual arrival clock: every PCM frame arrives
at its audio timestamp, while measured inference work advances a single worker
clock. This includes processing backlog without sleeping between frames. It is
a replay estimate, not a measurement of the browser/VAD/Smart Turn pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold().replace("ё", "е"), flags=re.UNICODE)


def distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else 0.0


def gpu_memory_mb():
    completed = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "--id=0"],
        capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if completed.returncode:
        raise RuntimeError("Could not sample GPU memory")
    return float(completed.stdout.strip())


class GigaEngine:
    streaming = False

    def __init__(self, args):
        from apps.backend.app.voice.providers import GigaAMSTTProvider
        from apps.backend.app.voice.runtime import configure_torch_threads

        configure_torch_threads(args.threads, 1)
        self.provider = GigaAMSTTProvider(args.model, args.device)
        asyncio.run(self.provider.preload())

    def recognize(self, audio):
        started = time.perf_counter()
        result = asyncio.run(self.provider.transcribe_pcm16(audio, "ru"))
        elapsed = (time.perf_counter() - started) * 1000
        return result.text, elapsed, elapsed, None, 0.0


class OnnxEngine:
    streaming = False

    def __init__(self, args):
        import onnx_asr
        import onnxruntime
        from apps.backend.app.voice.providers import GigaAMSTTProvider

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = args.threads
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        provider = "CPUExecutionProvider" if args.device == "cpu" else "CUDAExecutionProvider"
        if args.device == "cuda":
            self.dll_directories = []
            if sys.platform == "win32":
                for entry in sys.path:
                    for name in ("cublas", "cuda_runtime", "cufft"):
                        directory = Path(entry) / "nvidia" / name / "bin"
                        if directory.is_dir():
                            self.dll_directories.append(os.add_dll_directory(str(directory.resolve())))
            if args.cudnn_dir:
                self.dll_directories.append(os.add_dll_directory(str(args.cudnn_dir.resolve())))
                onnxruntime.preload_dlls(cuda=False, cudnn=True, directory=str(args.cudnn_dir.resolve()))
            onnxruntime.preload_dlls(cudnn=not bool(args.cudnn_dir), directory="")
        if provider not in onnxruntime.get_available_providers():
            raise RuntimeError(f"Requested provider {provider} is unavailable")
        self.model = onnx_asr.load_model(
            args.model, args.model_dir,
            quantization=None if args.quantization == "fp32" else args.quantization,
            providers=[provider], sess_options=options,
            preprocessor_config={"providers": ["CPUExecutionProvider"], "sess_options": options},
            resampler_config={"providers": ["CPUExecutionProvider"], "sess_options": options},
        )
        if args.device == "cuda":
            asr = self.model.asr
            sessions = [getattr(asr, name, None) for name in ("_model", "_encoder", "_decoder", "_joiner")]
            if any(provider not in session.get_providers() for session in sessions if session is not None):
                raise RuntimeError("CUDA initialization fell back to CPU; this is not a GPU benchmark")
            for session in sessions:
                if session is not None:
                    session.disable_fallback()
        session = getattr(self.model.asr, "_encoder", None) or self.model.asr._model
        self.execution_providers = session.get_providers()
        self.splitter = GigaAMSTTProvider("v3_rnnt", "cpu")

    def recognize(self, audio):
        import numpy as np

        started = time.perf_counter()
        chunks = self.splitter._split_pcm16_on_quiet(audio.data, overlap_seconds=.75)
        texts = [self.model.recognize(
            np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768,
            sample_rate=16000,
        ) for chunk in chunks]
        text = self.splitter._merge_overlapped_texts(texts)
        elapsed = (time.perf_counter() - started) * 1000
        return text, elapsed, elapsed, None, 0.0


class SherpaEngine:
    streaming = True

    def __init__(self, args):
        import sherpa_onnx

        directory = args.model_dir
        self.frame_samples = round(args.frame_ms * 16)
        self.language = args.language
        self.padding_ms = args.padding_ms
        common = dict(tokens=str(directory / "tokens.txt"), num_threads=args.threads,
                      provider=args.device, enable_endpoint_detection=False)
        if args.model == "t-one":
            self.recognizer = sherpa_onnx.OnlineRecognizer.from_t_one_ctc(
                model=str(directory / "model.onnx"), **common,
            )
        else:
            self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                encoder=str(directory / "encoder.int8.onnx"),
                decoder=str(directory / "decoder.int8.onnx"),
                joiner=str(directory / "joiner.int8.onnx"), feature_dim=128, **common,
            )

    def recognize(self, audio):
        import numpy as np

        samples = np.frombuffer(audio.data, dtype="<i2").astype(np.float32) / 32768
        stream = self.recognizer.create_stream()
        stream.set_option("language", self.language)
        busy_until = 0.0
        compute_ms = 0.0
        first_partial_ms = None
        peak_backlog_ms = 0.0
        for start in range(0, len(samples), self.frame_samples):
            end = min(start + self.frame_samples, len(samples))
            arrival_ms = end / 16
            began = time.perf_counter()
            stream.accept_waveform(16000, samples[start:end])
            while self.recognizer.is_ready(stream):
                self.recognizer.decode_stream(stream)
            partial = self.recognizer.get_result(stream)
            elapsed = (time.perf_counter() - began) * 1000
            compute_ms += elapsed
            busy_until = max(busy_until, arrival_ms) + elapsed
            peak_backlog_ms = max(peak_backlog_ms, busy_until - arrival_ms)
            if partial.strip() and first_partial_ms is None:
                first_partial_ms = busy_until
        began = time.perf_counter()
        # Padding is generated locally at stop, rather than waiting for another
        # silence interval. Both engines receive the same final padding.
        stream.accept_waveform(16000, np.zeros(round(self.padding_ms * 16), dtype=np.float32))
        stream.input_finished()
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)
        text = self.recognizer.get_result(stream).strip()
        elapsed = (time.perf_counter() - began) * 1000
        compute_ms += elapsed
        busy_until += elapsed
        tail_ms = max(0.0, busy_until - audio.duration_seconds * 1000)
        return text, compute_ms, tail_ms, first_partial_ms, peak_backlog_ms


def load_rows(manifest: Path, include_synthetic: bool):
    from apps.backend.app.voice.audio import decode_audio_file

    rows = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Manifest must be a nonempty JSON list")
    for row in rows:
        path = Path(row["audio"])
        if not path.is_absolute():
            path = manifest.parent / path
        yield row | {"audio": str(path.resolve())}, decode_audio_file(path)
    if include_synthetic:
        folder = ROOT / "output/tts-model-comparison/TeraTTSv2-listening-pack"
        pack = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        for case in pack["cases"]:
            if case["voice"] != "ru_f1":
                continue
            path = folder / case["file"]
            yield {"audio": str(path), "reference": case["text"],
                   "tags": ["synthetic", "terms-probe"]}, decode_audio_file(path)


def long_rows(rows):
    from apps.backend.app.voice.audio import Pcm16Audio

    available = sum(audio.duration_seconds + .2 for row, audio in rows
                    if "synthetic" not in row.get("tags", []))
    if available < 120:
        raise ValueError("--include-long requires at least 120 seconds of non-synthetic input")
    # Join complete public excerpts; never truncate a word or invent a reference.
    for target in (30, 60, 120):
        pieces, references = [], []
        duration = 0.0
        for row, audio in rows:
            if "synthetic" in row.get("tags", []):
                continue
            pieces.extend([audio.data, b"\x00\x00" * 3200])
            references.append(row["reference"])
            duration += audio.duration_seconds + .2
            if duration >= target:
                break
        yield {"audio": f"in-memory-public-concatenation-{target}s", "reference": " ".join(references),
               "tags": ["public", "human", "long-replay"]}, Pcm16Audio(b"".join(pieces))


def summarize(samples):
    def group(rows):
        seconds = sum(row["audio_seconds"] for row in rows)
        compute = sum(row["compute_ms"] for row in rows)
        return dict(
            count=len(rows), wer=(sum(row["word_errors"] for row in rows) / max(1, sum(row["words"] for row in rows))) if rows else None,
            audio_seconds=seconds, rtfx=seconds * 1000 / compute if compute else None,
            compute_p50_ms=percentile([row["compute_ms"] for row in rows], .50),
            compute_p95_ms=percentile([row["compute_ms"] for row in rows], .95),
            tail_p50_ms=percentile([row["tail_ms"] for row in rows], .50),
            tail_p95_ms=percentile([row["tail_ms"] for row in rows], .95),
        )
    return {
        "public": group([row for row in samples if "public" in row["tags"] and "long-replay" not in row["tags"]]),
        "synthetic": group([row for row in samples if "synthetic" in row["tags"]]),
        "long": group([row for row in samples if "long-replay" in row["tags"]]),
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["gigaam", "onnx", "sherpa"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--cudnn-dir", type=Path)
    parser.add_argument("--site-packages", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--quantization", choices=["fp32", "int8"], default="fp32")
    parser.add_argument("--threads", type=int, choices=[1, 2, 4, 8], default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument("--padding-ms", type=int, default=300)
    parser.add_argument("--pre-roll-ms", type=int, default=0)
    parser.add_argument("--language", default="ru")
    parser.add_argument("--include-synthetic", action="store_true")
    parser.add_argument("--include-long", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.repeats < 1 or args.frame_ms < 1 or args.padding_ms < 0 or args.pre_roll_ms < 0:
        parser.error("repeats and frame-ms must be positive; padding-ms must be nonnegative")
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    if args.engine != "gigaam" and not args.model_dir:
        parser.error("ONNX and sherpa engines require --model-dir")
    if args.site_packages:
        sys.path.insert(0, str(args.site_packages.resolve()))
    import psutil

    rows = list(load_rows(args.manifest.resolve(), args.include_synthetic))
    if args.limit:
        rows = rows[:args.limit]
    if args.include_long:
        rows.extend(long_rows(rows))
    if args.pre_roll_ms:
        from apps.backend.app.voice.audio import Pcm16Audio
        rows = [(row, Pcm16Audio(b"\x00\x00" * round(args.pre_roll_ms * 16) + audio.data))
                for row, audio in rows]
    began = time.perf_counter()
    engine = {"gigaam": GigaEngine, "onnx": OnnxEngine, "sherpa": SherpaEngine}[args.engine](args)
    load_ms = (time.perf_counter() - began) * 1000
    # Warm up every runtime before measuring; cold load is reported separately.
    engine.recognize(rows[0][1])
    process = psutil.Process()
    cpu_start = process.cpu_times()
    peak_rss = process.memory_info().rss
    gpu_peak = gpu_memory_mb() if args.device == "cuda" else None
    samples = []
    for index, (row, audio) in enumerate(rows):
        runs = [engine.recognize(audio) for _ in range(args.repeats)]
        transcripts = [run[0] for run in runs]
        reference, hypothesis = tokens(row["reference"]), tokens(transcripts[-1])
        samples.append(row | dict(
            transcript=transcripts[-1], deterministic=len(set(transcripts)) == 1,
            words=len(reference), word_errors=distance(reference, hypothesis),
            audio_seconds=audio.duration_seconds,
            compute_ms=statistics.median(run[1] for run in runs),
            tail_ms=statistics.median(run[2] for run in runs),
            first_partial_ms=statistics.median(run[3] for run in runs) if runs[0][3] is not None else None,
            peak_backlog_ms=max(run[4] for run in runs),
        ))
        peak_rss = max(peak_rss, process.memory_info().rss)
        if args.device == "cuda":
            gpu_peak = max(gpu_peak, gpu_memory_mb())
        if index % 6 == 0 or "long-replay" in row.get("tags", []):
            print(f"{index + 1}/{len(rows)} {audio.duration_seconds:.1f}s "
                  f"compute={samples[-1]['compute_ms']:.0f}ms tail={samples[-1]['tail_ms']:.0f}ms", flush=True)
    cpu_end = process.cpu_times()
    package_versions = {}
    for package in ("torch", "numpy", "onnxruntime", "onnxruntime-gpu", "onnx-asr", "sherpa-onnx", "gigaam"):
        try:
            package_versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    result = dict(
        schema_version=1, created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        configuration={key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        platform=platform.platform(), python=sys.version, packages=package_versions,
        manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        execution_providers=getattr(engine, "execution_providers", None),
        streaming=engine.streaming, timing="virtual-arrival replay" if engine.streaming else "post-stop batch",
        limitations=["Public reading speech and optional synthetic speech are not a personal microphone quality gate.",
                      "Tail excludes VAD, Smart Turn, browser capture, WebSocket and LLM latency."],
        load_ms=load_ms, peak_rss_mb=peak_rss / 1024**2,
        gpu_device_memory_observed_peak_mb=gpu_peak,
        cpu_seconds=cpu_end.user + cpu_end.system - cpu_start.user - cpu_start.system,
        summary=summarize(samples), samples=samples,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
