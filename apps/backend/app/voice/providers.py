import asyncio
import array
import io
import logging
import math
import re
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from apps.backend.app.voice.audio import Pcm16Audio, write_pcm16_wav
from apps.backend.app.voice.delivery import (
    MAX_SPEECH_TEMPO,
    MIN_SPEECH_TEMPO,
    SpeechEmphasis,
    SpeechPace,
)
from apps.backend.app.voice.style import VoiceStyle

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class STTResult:
    text: str
    language: str
    duration_ms: int
    provider: str
    model: str | None = None
    raw_text: str | None = None
    corrections: tuple[dict[str, object], ...] = ()
    confidence: float | None = None
    fallback: bool = False
    fallback_reason: str | None = None


@dataclass(frozen=True)
class TTSResult:
    audio_path: Path
    duration_ms: int
    provider: str
    voice: str
    chunks_count: int = 1
    audio_duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class TTSRequest:
    text: str
    language: str
    voice: str
    style: VoiceStyle | str = VoiceStyle.AUTO
    pace: SpeechPace | str = SpeechPace.NORMAL
    tempo: float = 1.0
    emphasis: SpeechEmphasis | str = SpeechEmphasis.NONE
    pause_before_ms: int = 0
    pause_after_ms: int = 100
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"


@dataclass(frozen=True, slots=True)
class AudioChunk:
    data: bytes
    format: str
    sequence: int
    is_final: bool = False
    metadata: dict | None = None


class STTProvider:
    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        raise NotImplementedError

    async def preload(self) -> None:
        return None

    async def transcribe_pcm16(self, audio: Pcm16Audio, language: str) -> STTResult:
        with tempfile.TemporaryDirectory(prefix="neuroasist-stt-") as directory:
            path = Path(directory) / "input.wav"
            write_pcm16_wav(path, audio)
            return await self.transcribe(path, language)


class TTSProvider:
    @property
    def name(self) -> str:
        return self.__class__.__name__.removesuffix("Provider").lower()

    @property
    def output_format(self) -> str:
        return "wav"

    @property
    def file_extension(self) -> str:
        return ".wav"

    async def preload(self) -> None:
        return None

    def resolve_voice(self, language: str, requested_voice: str | None = None) -> str:
        return requested_voice or language

    async def synthesize(
        self, text: str, voice: str, output_path: Path, style: VoiceStyle | str = VoiceStyle.AUTO
    ) -> TTSResult:
        raise NotImplementedError

    async def stream(self, request: TTSRequest):
        raise NotImplementedError


class MockSTTProvider(STTProvider):
    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        return STTResult(
            text="Тестовое голосовое сообщение",
            language="ru" if language == "auto" else language,
            duration_ms=0,
            provider="mock",
            model="mock",
            confidence=1.0,
        )


class MockTTSProvider(TTSProvider):
    @property
    def name(self) -> str:
        return "mock"

    async def stream(self, request: TTSRequest):
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 1600)
        yield AudioChunk(output.getvalue(), "wav", 0, is_final=True)

    async def synthesize(
        self, text: str, voice: str, output_path: Path, style: VoiceStyle | str = VoiceStyle.AUTO
    ) -> TTSResult:
        started = time.perf_counter()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 1600)
        return TTSResult(
            audio_path=output_path,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="mock",
            voice=voice,
            audio_duration_seconds=0.1,
        )


class FasterWhisperSTTProvider(STTProvider):
    _RUSSIAN_PROMPT = (
        "Это живой разговор на русском языке. Распознавай речь дословно, "
        "сохраняй смысл, не переводи и не выдумывай слова."
    )

    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._model = None
        self._selected_device: str | None = None
        self._selected_compute_type: str | None = None

    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language, started)

    async def preload(self) -> None:
        await asyncio.to_thread(self._ensure_model)

    def _ensure_model(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed") from exc

        if self._model is None:
            candidates = [(self._device, self._compute_type)]
            if self._device == "auto":
                candidates = [("cuda", "int8_float16"), ("cpu", "int8")]
            last_error: Exception | None = None
            for device, compute_type in candidates:
                try:
                    self._model = WhisperModel(
                        self._model_name,
                        device=device,
                        compute_type=compute_type,
                    )
                    self._selected_device = device
                    self._selected_compute_type = compute_type
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "FasterWhisper model load failed: model=%s device=%s compute_type=%s error_type=%s",
                        self._model_name,
                        device,
                        compute_type,
                        type(exc).__name__,
                    )
            if self._model is None:
                raise RuntimeError("faster-whisper model could not be loaded") from last_error
        return self._model

    def _transcribe_sync(self, audio_path: Path, language: str, started: float) -> STTResult:
        try:
            return self._transcribe_with_current_model(audio_path, language, started)
        except Exception as exc:
            if not self._should_retry_stt_on_cpu(exc):
                raise
            logger.info(
                "FasterWhisper CUDA runtime failed, retrying on CPU: model=%s "
                "device=%s compute_type=%s error_type=%s",
                self._model_name,
                self._selected_device,
                self._selected_compute_type,
                type(exc).__name__,
            )
            self._model = None
            self._device = "cpu"
            self._compute_type = "int8"
            self._selected_device = None
            self._selected_compute_type = None
            return self._transcribe_with_current_model(audio_path, language, started)

    def _transcribe_with_current_model(self, audio_path: Path, language: str, started: float) -> STTResult:
        model = self._ensure_model()
        selected_language = None if language == "auto" else language
        segments, info = model.transcribe(
            str(audio_path),
            language=selected_language,
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 250,
            },
            initial_prompt=self._initial_prompt(selected_language),
            no_speech_threshold=0.45,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
        )
        segment_list = list(segments)
        text = " ".join(segment.text.strip() for segment in segment_list).strip()
        confidence_values: list[float] = []
        for segment in segment_list:
            avg_logprob = getattr(segment, "avg_logprob", None)
            no_speech_prob = getattr(segment, "no_speech_prob", 0.0)
            if avg_logprob is None:
                continue
            confidence_values.append(
                max(0.0, min(1.0, math.exp(max(-10.0, min(0.0, float(avg_logprob))))))
                * max(0.0, min(1.0, 1.0 - float(no_speech_prob)))
            )
        detected_language = getattr(info, "language", None) or selected_language or "auto"
        return STTResult(
            text=text,
            language=detected_language,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="faster_whisper",
            model=self._model_name,
            confidence=(sum(confidence_values) / len(confidence_values)) if confidence_values else None,
        )

    def _initial_prompt(self, language: str | None) -> str | None:
        if language == "ru":
            return self._RUSSIAN_PROMPT
        return None

    def _should_retry_stt_on_cpu(self, exc: Exception) -> bool:
        if self._device != "auto" or self._selected_device != "cuda":
            return False
        message = str(exc).lower()
        cuda_markers = (
            "cuda",
            "cublas",
            "cudnn",
            "cufft",
            "curand",
            "cusolver",
            "cusparse",
            ".dll",
            "library",
        )
        return any(marker in message for marker in cuda_markers)


class Qwen3ASRProvider(STTProvider):
    """Optional local Qwen3-ASR adapter used for Russian benchmark/fallback runs.

    ``qwen-asr`` is intentionally imported lazily. The default installation
    stays lightweight, while a machine with the optional package can select
    ``qwen3_asr`` through ``VOICE_STT_PROVIDER`` or the fallback setting.
    """

    _LANGUAGES = {"ru": "Russian", "en": "English"}

    def __init__(self, model_name: str, device: str) -> None:
        if device not in {"cpu", "cuda", "auto"}:
            raise ValueError("VOICE_STT_DEVICE must be one of: cpu, cuda, auto")
        self._model_name = (
            model_name
            if model_name and model_name not in {"v3_rnnt", "v3_e2e_rnnt"}
            else "Qwen/Qwen3-ASR-1.7B"
        )
        self._device = device
        self._model = None
        self._selected_device: str | None = None
        self._load_lock = threading.Lock()

    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language, started)

    async def preload(self) -> None:
        await asyncio.to_thread(self._ensure_model)

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "provider": "qwen3_asr",
            "model": self._model_name,
            "device": self._selected_device or self._device,
        }

    def _ensure_model(self):
        try:
            import torch
            from qwen_asr import Qwen3ASRModel
        except ImportError as exc:
            raise RuntimeError(
                "Qwen3-ASR is not installed; install the optional qwen-asr package"
            ) from exc

        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            selected_device = self._device
            if selected_device == "auto":
                selected_device = "cuda:0" if torch.cuda.is_available() else "cpu"
            elif selected_device == "cuda":
                selected_device = "cuda:0"
            dtype = torch.bfloat16 if selected_device.startswith("cuda") else torch.float32
            self._model = Qwen3ASRModel.from_pretrained(
                self._model_name,
                dtype=dtype,
                device_map=selected_device,
                max_inference_batch_size=1,
                max_new_tokens=256,
            )
            self._selected_device = selected_device
        return self._model

    def _transcribe_sync(self, audio_path: Path, language: str, started: float) -> STTResult:
        model = self._ensure_model()
        selected_language = self._LANGUAGES.get(language)
        results = model.transcribe(audio=str(audio_path), language=selected_language)
        first = results[0] if isinstance(results, (list, tuple)) else results
        text = str(getattr(first, "text", first)).strip()
        detected_language = str(getattr(first, "language", None) or language or "auto")
        return STTResult(
            text=text,
            language=detected_language,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="qwen3_asr",
            model=self._model_name,
        )


class FallbackSTTProvider(STTProvider):
    """Run a configured secondary model only when the primary looks uncertain."""

    def __init__(
        self,
        primary: STTProvider,
        fallback: STTProvider,
        *,
        confidence_threshold: float = 0.60,
        min_rms: float = 0.008,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.confidence_threshold = confidence_threshold
        self.min_rms = min_rms

    async def preload(self) -> None:
        # Keep the secondary model cold until it is actually needed. This is
        # important for a live session's startup time and resident memory.
        await self.primary.preload()

    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        primary_result = await self.primary.transcribe(audio_path, language)
        reason = self._fallback_reason(primary_result, None)
        if reason is None:
            return primary_result
        return await self._run_fallback(primary_result, audio_path, language, reason)

    async def transcribe_pcm16(self, audio: Pcm16Audio, language: str) -> STTResult:
        primary_result = await self.primary.transcribe_pcm16(audio, language)
        reason = self._fallback_reason(primary_result, self._rms(audio))
        if reason is None:
            return primary_result
        try:
            fallback_result = await self.fallback.transcribe_pcm16(audio, language)
        except Exception as exc:
            logger.warning(
                "STT fallback failed; keeping primary result: provider=%s error_type=%s",
                getattr(self.fallback, "name", self.fallback.__class__.__name__),
                type(exc).__name__,
            )
            return replace(primary_result, fallback_reason=f"{reason}:unavailable")
        return replace(fallback_result, fallback=True, fallback_reason=reason)

    async def _run_fallback(
        self,
        primary_result: STTResult,
        audio_path: Path,
        language: str,
        reason: str,
    ) -> STTResult:
        try:
            fallback_result = await self.fallback.transcribe(audio_path, language)
        except Exception as exc:
            logger.warning(
                "STT fallback failed; keeping primary result: provider=%s error_type=%s",
                self.fallback.__class__.__name__,
                type(exc).__name__,
            )
            return replace(primary_result, fallback_reason=f"{reason}:unavailable")
        return replace(fallback_result, fallback=True, fallback_reason=reason)

    def _fallback_reason(self, result: STTResult, rms: float | None) -> str | None:
        if not result.text.strip():
            return "empty_result"
        if result.confidence is not None and result.confidence < self.confidence_threshold:
            return "low_confidence"
        if rms is not None and rms < self.min_rms:
            return "low_snr"
        return None

    @staticmethod
    def _rms(audio: Pcm16Audio) -> float:
        samples = array.array("h")
        samples.frombytes(audio.data)
        if not samples:
            return 0.0
        return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0


class GigaAMSTTProvider(STTProvider):
    """Russian-first local ASR backed by GigaAM v3."""

    _SAMPLE_RATE = 16000
    _MAX_SHORT_SECONDS = 24

    def __init__(self, model_name: str, device: str) -> None:
        if device not in {"cpu", "cuda", "auto"}:
            raise ValueError("VOICE_STT_DEVICE must be one of: cpu, cuda, auto")
        self._model_name = model_name
        self._device = device
        self._model = None
        self._selected_device: str | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._warmup_lock = threading.Lock()
        self._warmed_up = False
        self._warmup_duration_ms: int | None = None

    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language, started)

    async def transcribe_pcm16(self, audio: Pcm16Audio, language: str) -> STTResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._transcribe_pcm_sync, audio, language, started)

    async def preload(self) -> None:
        await asyncio.to_thread(self._preload_sync)

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "provider": "gigaam",
            "model": self._model_name,
            "device": self._selected_device or self._device,
            "warmed_up": self._warmed_up,
            "warmup_duration_ms": self._warmup_duration_ms,
        }

    def _preload_sync(self) -> None:
        self._ensure_model()
        if self._warmed_up:
            return
        with self._warmup_lock:
            if self._warmed_up:
                return
            started = time.perf_counter()
            # A short silence exercises preprocessing, encoder and RNNT decode
            # without persisting microphone audio or creating a temporary WAV.
            model = self._ensure_model()
            if all(hasattr(model, name) for name in ("_device", "_dtype", "_decode", "forward")):
                self._transcribe_pcm_sync(
                    Pcm16Audio(b"\x00\x00" * 6_400),
                    "ru",
                    started,
                )
            self._warmup_duration_ms = int((time.perf_counter() - started) * 1000)
            self._warmed_up = True
            logger.info(
                "GigaAM STT warmed up: model=%s device=%s duration_ms=%s",
                self._model_name,
                self._selected_device,
                self._warmup_duration_ms,
            )

    def _ensure_model(self):
        try:
            import gigaam
        except ImportError as exc:
            raise RuntimeError("GigaAM is not installed") from exc

        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            candidates = [self._device]
            if self._device == "auto":
                candidates = ["cuda", "cpu"]
            last_error: Exception | None = None
            for device in candidates:
                try:
                    self._model = gigaam.load_model(
                        self._model_name,
                        device=device,
                        fp16_encoder=device == "cuda",
                        use_flash=False,
                    )
                    self._selected_device = device
                    logger.info(
                        "GigaAM STT model loaded: model=%s device=%s",
                        self._model_name,
                        device,
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "GigaAM model load failed: model=%s device=%s error_type=%s",
                        self._model_name,
                        device,
                        type(exc).__name__,
                    )
            if self._model is None:
                raise RuntimeError("GigaAM model could not be loaded") from last_error
        return self._model

    def _transcribe_sync(self, audio_path: Path, language: str, started: float) -> STTResult:
        with self._inference_lock:
            try:
                text = self._transcribe_with_current_model(audio_path)
            except Exception as exc:
                if not self._should_retry_on_cpu(exc):
                    raise
                logger.info(
                    "GigaAM CUDA runtime failed, retrying on CPU: model=%s error_type=%s",
                    self._model_name,
                    type(exc).__name__,
                )
                self._model = None
                self._device = "cpu"
                self._selected_device = None
                text = self._transcribe_with_current_model(audio_path)
        return STTResult(
            text=text,
            language="ru" if language == "auto" else language,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="gigaam",
            model=self._model_name,
        )

    def _transcribe_pcm_sync(
        self,
        audio: Pcm16Audio,
        language: str,
        started: float,
    ) -> STTResult:
        with self._inference_lock:
            try:
                text = self._transcribe_pcm_with_current_model(audio)
            except Exception as exc:
                if not self._should_retry_on_cpu(exc):
                    raise
                logger.info(
                    "GigaAM CUDA runtime failed, retrying PCM inference on CPU: model=%s error_type=%s",
                    self._model_name,
                    type(exc).__name__,
                )
                self._model = None
                self._device = "cpu"
                self._selected_device = None
                text = self._transcribe_pcm_with_current_model(audio)
        return STTResult(
            text=text,
            language="ru" if language == "auto" else language,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="gigaam",
            model=self._model_name,
        )

    def _transcribe_with_current_model(self, audio_path: Path) -> str:
        model = self._ensure_model()
        try:
            return self._transcribe_short(model, audio_path)
        except ValueError as exc:
            if "too long wav" not in str(exc).lower():
                raise
        return self._transcribe_long(model, audio_path)

    def _transcribe_pcm_with_current_model(self, audio: Pcm16Audio) -> str:
        model = self._ensure_model()
        max_bytes = self._MAX_SHORT_SECONDS * self._SAMPLE_RATE * 2
        if len(audio.data) <= max_bytes:
            return self._transcribe_short_pcm(model, audio.data)
        texts = [
            self._transcribe_short_pcm(model, chunk)
            for chunk in self._split_pcm16_on_quiet(audio.data, overlap_seconds=0.75)
        ]
        return self._merge_overlapped_texts(texts)

    @staticmethod
    def _transcribe_short_pcm(model: Any, pcm16: bytes) -> str:
        import torch

        samples = array.array("h")
        samples.frombytes(pcm16)
        waveform = torch.tensor(samples, dtype=torch.float32).div_(32768.0)
        waveform = waveform.to(model._device).to(model._dtype).unsqueeze(0)
        length = torch.tensor([waveform.shape[-1]], device=model._device)
        with torch.inference_mode():
            encoded, encoded_len = model.forward(waveform, length)
            text, _words = model._decode(encoded, encoded_len, length, False)[0]
        return str(text).strip()

    @staticmethod
    def _transcribe_short(model: Any, audio_path: Path) -> str:
        result = model.transcribe(str(audio_path))
        return str(getattr(result, "text", result)).strip()

    def _transcribe_long(self, model: Any, audio_path: Path) -> str:
        pcm16 = self._decode_pcm16(audio_path)
        chunks = self._split_pcm16_on_quiet(pcm16, overlap_seconds=0.75)
        texts: list[str] = []
        with tempfile.TemporaryDirectory(prefix="neuroasist-gigaam-") as temp_dir:
            for index, chunk in enumerate(chunks):
                chunk_path = Path(temp_dir) / f"chunk-{index:03d}.wav"
                with wave.open(str(chunk_path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(self._SAMPLE_RATE)
                    audio.writeframes(chunk)
                text = self._transcribe_short(model, chunk_path)
                if text:
                    texts.append(text)
        return self._merge_overlapped_texts(texts)

    def _decode_pcm16(self, audio_path: Path) -> bytes:
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(audio_path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(self._SAMPLE_RATE),
            "-",
        ]
        completed = subprocess.run(command, capture_output=True, check=False)
        if completed.returncode != 0 or not completed.stdout:
            raise RuntimeError("Could not decode long audio for GigaAM")
        return completed.stdout

    def _split_pcm16_on_quiet(self, pcm16: bytes, *, overlap_seconds: float = 0.0) -> list[bytes]:
        samples = array.array("h")
        samples.frombytes(pcm16)
        max_samples = self._MAX_SHORT_SECONDS * self._SAMPLE_RATE
        if len(samples) <= max_samples:
            return [pcm16]

        min_chunk = 16 * self._SAMPLE_RATE
        max_chunk = 23 * self._SAMPLE_RATE
        min_tail = 5 * self._SAMPLE_RATE
        frame = self._SAMPLE_RATE // 10
        overlap_samples = max(0, round(overlap_seconds * self._SAMPLE_RATE))
        chunks: list[bytes] = []
        start = 0
        while len(samples) - start > max_samples:
            search_start = start + min_chunk
            search_end = min(start + max_chunk, len(samples) - min_tail)
            if search_end <= search_start:
                cut = min(start + max_chunk, len(samples))
            else:
                candidates = range(search_start, search_end - frame + 1, frame)
                quiet_start = min(
                    candidates,
                    key=lambda offset: sum(value * value for value in samples[offset : offset + frame]),
                )
                cut = quiet_start + frame // 2
            chunks.append(samples[max(0, start - overlap_samples):cut].tobytes())
            start = cut
        if start < len(samples):
            chunks.append(samples[max(0, start - overlap_samples):].tobytes())
        return chunks

    @staticmethod
    def _merge_overlapped_texts(texts: list[str]) -> str:
        merged: list[str] = []
        for text in texts:
            tokens = text.split()
            if not tokens:
                continue
            overlap = 0
            max_overlap = min(8, len(merged), len(tokens))
            for size in range(max_overlap, 0, -1):
                if [item.casefold() for item in merged[-size:]] == [item.casefold() for item in tokens[:size]]:
                    overlap = size
                    break
            merged.extend(tokens[overlap:])
        return " ".join(merged).strip()

    def _should_retry_on_cpu(self, exc: Exception) -> bool:
        if self._device != "auto" or self._selected_device != "cuda":
            return False
        message = str(exc).lower()
        return any(
            marker in message
            for marker in ("cuda", "cublas", "cudnn", "out of memory", "driver")
        )


def one_pole_highpass(samples: Any, sample_rate: int, cutoff_hz: float):
    """Closed-form equivalent of ``y[n] = a * (y[n-1] + x[n] - x[n-1])``.

    The recurrence used to be evaluated in a Python loop over every sample on
    the live TTS path, which costs tens of milliseconds per segment. Expanding
    it gives ``y[i] = a^(i+1) * (carry + sum_j a^-j * d[j])``, which vectorises,
    but ``a^-j`` overflows on long signals. Working in blocks keeps that factor
    inside a narrow range, so the result matches the scalar loop to well below
    the int16 quantisation step while numpy does the work.
    """
    import numpy as np

    if cutoff_hz <= 0 or sample_rate <= 0 or len(samples) < 2:
        return samples
    source = np.asarray(samples)
    signal = source.astype(np.float64, copy=False)
    rc = 1.0 / (2.0 * np.pi * cutoff_hz)
    alpha = rc / (rc + 1.0 / sample_rate)
    decay = -float(np.log(alpha)) if 0.0 < alpha < 1.0 else 0.0
    if decay <= 0.0:
        return samples
    # Cap the spread of a^-j at e^18 so float64 keeps ~8 significant digits.
    block = int(min(8192.0, max(2.0, 1.0 + 18.0 / decay)))

    deltas = np.empty_like(signal)
    deltas[0] = 0.0
    np.subtract(signal[1:], signal[:-1], out=deltas[1:])

    output = np.empty_like(signal)
    output[0] = signal[0]
    carry = float(signal[0])
    index = 1
    total = len(signal)
    while index < total:
        span = min(block, total - index)
        growth = alpha ** np.arange(span, dtype=np.float64)
        chunk = (alpha * growth) * (
            carry + np.cumsum(deltas[index : index + span] / growth)
        )
        output[index : index + span] = chunk
        carry = float(chunk[-1])
        index += span
    if np.issubdtype(source.dtype, np.floating):
        return output.astype(source.dtype, copy=False)
    return output


def waveform_to_wav_bytes(waveform: Any, sample_rate: int) -> bytes:
    import numpy as np

    value = waveform
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        samples = value.numpy()
    else:
        samples = np.asarray(value)
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(pcm.tobytes())
    return output.getvalue()


def wav_duration_seconds(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as audio:
        frames = audio.getnframes()
        rate = audio.getframerate()
        if frames <= 0 or rate <= 0:
            raise RuntimeError("TTS provider returned zero-duration audio")
        return frames / rate


def apply_wav_delivery(
    wav_bytes: bytes,
    *,
    tempo: float = 1.0,
    pause_before_ms: int = 0,
    pause_after_ms: int = 0,
    postprocess: bool = False,
    loudness_target_dbfs: float = -18.0,
    peak_ceiling_dbfs: float = -1.0,
    highpass_cutoff_hz: float = 60.0,
) -> bytes:
    """Apply pitch-preserving tempo and explicit silence to mono PCM16 WAV."""
    import numpy as np

    tempo = max(MIN_SPEECH_TEMPO, min(MAX_SPEECH_TEMPO, float(tempo)))
    with wave.open(io.BytesIO(wav_bytes), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        pcm = source.readframes(source.getnframes())
    if channels != 1 or sample_width != 2 or not pcm:
        return wav_bytes

    samples = np.frombuffer(pcm, dtype="<i2").copy()
    if abs(tempo - 1.0) >= 0.001:
        try:
            import av

            frame = av.AudioFrame(format="s16", layout="mono", samples=len(samples))
            frame.sample_rate = sample_rate
            frame.planes[0].update(samples.tobytes())
            graph = av.filter.Graph()
            source_filter = graph.add(
                "abuffer",
                args=f"sample_rate={sample_rate}:sample_fmt=s16:channel_layout=mono",
            )
            tempo_filter = graph.add("atempo", f"{tempo:.6f}")
            sink_filter = graph.add("abuffersink")
            source_filter.link_to(tempo_filter)
            tempo_filter.link_to(sink_filter)
            graph.configure()
            graph.push(frame)
            graph.push(None)
            rendered: list[Any] = []
            while True:
                try:
                    rendered.append(graph.pull())
                except (av.error.BlockingIOError, EOFError):
                    break
            if rendered:
                samples = np.concatenate(
                    [item.to_ndarray().reshape(-1).astype("<i2", copy=False) for item in rendered]
                )
        except Exception:
            logger.warning(
                "Could not apply pitch-preserving TTS tempo; using original audio: tempo=%s",
                tempo,
                exc_info=True,
            )

    if postprocess and len(samples):
        rendered = samples.astype(np.float32) / 32768.0
        rendered -= float(np.mean(rendered))
        if highpass_cutoff_hz > 0 and len(rendered) > 1:
            rendered = one_pole_highpass(rendered, sample_rate, highpass_cutoff_hz)
        active = np.abs(rendered) >= 10 ** (-45 / 20)
        if active.any():
            rms = float(np.sqrt(np.mean(np.square(rendered[active]))))
            peak = float(np.max(np.abs(rendered)))
            if rms > 0 and peak > 0:
                target = 10 ** (loudness_target_dbfs / 20)
                ceiling = 10 ** (peak_ceiling_dbfs / 20)
                rendered *= min(target / rms, ceiling / peak)
        fade_samples = min(max(1, round(sample_rate * 0.008)), len(rendered) // 2)
        if fade_samples:
            fade = np.linspace(0.0, 1.0, fade_samples, endpoint=False, dtype=np.float32)
            rendered[:fade_samples] *= fade
            rendered[-fade_samples:] *= fade[::-1]
        samples = (np.clip(rendered, -1.0, 1.0) * 32767).astype("<i2")

    before = np.zeros(max(0, round(sample_rate * pause_before_ms / 1000)), dtype="<i2")
    after = np.zeros(max(0, round(sample_rate * pause_after_ms / 1000)), dtype="<i2")
    delivered = np.concatenate((before, samples, after))
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(delivered.tobytes())
    return output.getvalue()



def split_tts_chunks(text: str, max_chars: int = 90, max_words: int = 18) -> list[str]:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return []
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?…。！？])\s+", normalized)
        if part.strip()
    ]
    chunks: list[str] = []
    for sentence in sentences or [normalized]:
        chunks.extend(_split_tts_sentence(sentence, max_chars, max_words))
    return _merge_short_tail(chunks, max_chars, max_words) or [normalized]


def _tts_chunk_fits(text: str, max_chars: int, max_words: int) -> bool:
    return len(text) <= max_chars and len(text.split()) <= max_words


def _minimum_tts_duration_seconds(text: str) -> float:
    words = len(text.split())
    chars = len(text)
    if words <= 2 and chars <= 16:
        return 0.15
    estimated_duration = max(0.25, min(words * 0.12, chars * 0.015))
    return estimated_duration * 0.85


def _split_tts_sentence(text: str, max_chars: int, max_words: int) -> list[str]:
    if _tts_chunk_fits(text, max_chars, max_words):
        return [text]
    for pattern in (r"(?<=[;:])\s+", r"(?<=,)\s+"):
        parts = [part.strip() for part in re.split(pattern, text) if part.strip()]
        if len(parts) > 1:
            chunks: list[str] = []
            for part in parts:
                if _tts_chunk_fits(part, max_chars, max_words):
                    chunks.append(part)
                else:
                    chunks.extend(_split_long_tts_text(part, max_chars, max_words))
            return _merge_short_tail(chunks, max_chars, max_words)
    return _split_long_tts_text(text, max_chars, max_words)


def _split_long_tts_text(text: str, max_chars: int, max_words: int) -> list[str]:
    chunks: list[str] = []
    current_words: list[str] = []
    for word in text.split():
        candidate_words = [*current_words, word]
        candidate_text = " ".join(candidate_words)
        if current_words and not _tts_chunk_fits(candidate_text, max_chars, max_words):
            chunks.append(" ".join(current_words))
            current_words = [word]
        else:
            current_words = candidate_words
    if current_words:
        chunks.append(" ".join(current_words))
    return _merge_short_tail(chunks, max_chars, max_words)


def _merge_short_tail(chunks: list[str], max_chars: int, max_words: int) -> list[str]:
    if len(chunks) >= 2 and len(chunks[-1].split()) <= 3:
        candidate = f"{chunks[-2]} {chunks[-1]}"
        if _tts_chunk_fits(candidate, int(max_chars * 1.25), max_words):
            chunks[-2] = candidate
            chunks.pop()
    return chunks
