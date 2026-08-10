from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TurnDetectionResult:
    complete: bool
    confidence: float
    provider: str
    latency_ms: float
    fallback: bool = False
    error: str | None = None


class SmartTurnDetector:
    """Optional local Smart Turn v3.2 adapter with a patient live fallback."""

    name = "smart-turn-v3.2"

    def __init__(self, model_path: Path | None, *, timeout_seconds: float = 0.5) -> None:
        self._model_path = model_path
        self._timeout = timeout_seconds
        self._session = None
        self._feature_extractor = None
        self.error: str | None = None
        if model_path is None or not model_path.is_file():
            self.error = "Smart Turn model is not installed"
            return
        try:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(
                str(model_path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self._feature_extractor = _WhisperLogMelExtractor()
        except Exception as exc:
            self.error = f"Could not load Smart Turn: {exc}"

    @property
    def ready(self) -> bool:
        return self._session is not None and self._feature_extractor is not None

    async def analyze(self, pcm16: bytes, sample_rate: int) -> TurnDetectionResult:
        started = time.perf_counter()
        if not self.ready or sample_rate != 16000:
            return TurnDetectionResult(
                complete=False,
                confidence=0.5,
                provider="heuristic",
                latency_ms=(time.perf_counter() - started) * 1000,
                fallback=True,
                error=self.error if not self.ready else "Smart Turn requires 16 kHz PCM",
            )
        try:
            probability = await asyncio.wait_for(
                asyncio.to_thread(self._predict, pcm16),
                timeout=self._timeout,
            )
            return TurnDetectionResult(
                complete=probability > 0.5,
                confidence=probability if probability > 0.5 else 1.0 - probability,
                provider=self.name,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except TimeoutError:
            return TurnDetectionResult(
                complete=False,
                confidence=0.5,
                provider="heuristic",
                latency_ms=(time.perf_counter() - started) * 1000,
                fallback=True,
                error="Smart Turn inference timed out",
            )
        except Exception as exc:
            return TurnDetectionResult(
                complete=False,
                confidence=0.5,
                provider="heuristic",
                latency_ms=(time.perf_counter() - started) * 1000,
                fallback=True,
                error=str(exc),
            )

    def _predict(self, pcm16: bytes) -> float:
        import numpy as np

        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        maximum = 8 * 16000
        if audio.size > maximum:
            audio = audio[-maximum:]
        elif audio.size < maximum:
            audio = np.pad(audio, (maximum - audio.size, 0))
        features = np.expand_dims(self._feature_extractor(audio), axis=0)
        outputs = self._session.run(None, {"input_features": features})
        return max(0.0, min(1.0, float(outputs[0][0].item())))


class _WhisperLogMelExtractor:
    """NumPy implementation of Whisper's 80-bin, 10 ms log-mel frontend."""

    sample_rate = 16000
    n_fft = 400
    hop_length = 160
    n_mels = 80
    frames = 800

    def __init__(self) -> None:
        import numpy as np

        self._window = np.hanning(self.n_fft + 1)[:-1].astype(np.float32)
        self._filters = self._mel_filters(np)

    def __call__(self, audio):
        import numpy as np

        audio = audio.astype(np.float32)
        variance = float(np.var(audio))
        if variance > 0:
            audio = (audio - float(np.mean(audio))) / np.sqrt(variance + 1e-7)
        padded = np.pad(audio, (self.n_fft // 2, self.n_fft // 2), mode="reflect")
        windows = np.lib.stride_tricks.sliding_window_view(padded, self.n_fft)[:: self.hop_length]
        windows = windows[: self.frames] * self._window
        power = np.abs(np.fft.rfft(windows, axis=1)) ** 2
        mel = self._filters @ power.T
        log_spec = np.log10(np.maximum(mel, 1e-10))
        log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
        return ((log_spec + 4.0) / 4.0).astype(np.float32)

    @classmethod
    def _mel_filters(cls, np):
        fft_freqs = np.linspace(0.0, cls.sample_rate / 2, 1 + cls.n_fft // 2)
        min_log_hz = 1000.0
        min_log_mel = 15.0
        logstep = np.log(6.4) / 27.0

        def hz_to_mel(freq):
            freq = np.asarray(freq)
            linear = freq / (200.0 / 3.0)
            return np.where(
                freq >= min_log_hz,
                min_log_mel + np.log(np.maximum(freq, min_log_hz) / min_log_hz) / logstep,
                linear,
            )

        def mel_to_hz(mel):
            mel = np.asarray(mel)
            linear = (200.0 / 3.0) * mel
            return np.where(
                mel >= min_log_mel,
                min_log_hz * np.exp(logstep * (mel - min_log_mel)),
                linear,
            )

        mel_points = np.linspace(
            hz_to_mel(0.0),
            hz_to_mel(cls.sample_rate / 2),
            cls.n_mels + 2,
        )
        hz_points = mel_to_hz(mel_points)
        ramps = hz_points[:, None] - fft_freqs[None, :]
        fdiff = np.diff(hz_points)
        lower = -ramps[:-2] / fdiff[:-1, None]
        upper = ramps[2:] / fdiff[1:, None]
        weights = np.maximum(0.0, np.minimum(lower, upper))
        weights *= (2.0 / (hz_points[2:] - hz_points[:-2]))[:, None]
        return weights.astype(np.float32)
