import asyncio
import io
import logging
import os
import re
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class STTResult:
    text: str
    language: str
    duration_ms: int
    provider: str
    model: str | None = None


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

    async def synthesize(self, text: str, voice: str, output_path: Path) -> TTSResult:
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

    async def synthesize(self, text: str, voice: str, output_path: Path) -> TTSResult:
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
        text = " ".join(segment.text.strip() for segment in segments).strip()
        detected_language = getattr(info, "language", None) or selected_language or "auto"
        return STTResult(
            text=text,
            language=detected_language,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="faster_whisper",
            model=self._model_name,
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


class SileroTTSProvider(TTSProvider):
    def __init__(
        self,
        model: str = "v5_5_ru",
        speaker: str = "xenia",
        sample_rate: int = 24000,
        device: str = "cpu",
        cpu_threads: int = 4,
        warmup: bool = True,
        timeout_seconds: float = 10.0,
        model_loader: Callable[[], Any] | None = None,
    ) -> None:
        if device not in {"cpu", "cuda", "auto"}:
            raise ValueError("VOICE_SILERO_DEVICE must be one of: cpu, cuda, auto")
        self.model_name = model
        self.speaker = speaker
        self.sample_rate = sample_rate
        self.requested_device = device
        self.cpu_threads = cpu_threads
        self.warmup_enabled = warmup
        self.timeout_seconds = timeout_seconds
        self._model_loader = model_loader
        self._model = None
        self._torch = None
        self._selected_device: str | None = None
        self._available_speakers: set[str] | None = None
        self._load_lock = asyncio.Lock()
        self._infer_lock = asyncio.Lock()
        self._warmed_up = False

    @property
    def name(self) -> str:
        return "silero"

    def resolve_voice(self, language: str, requested_voice: str | None = None) -> str:
        if requested_voice and requested_voice in self.available_speakers:
            return requested_voice
        return self.speaker

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model_name,
            "speaker": self.speaker,
            "device": self._selected_device or self.requested_device,
            "sample_rate": self.sample_rate,
        }

    @property
    def available_speakers(self) -> list[str]:
        if self._available_speakers is not None:
            return sorted(self._available_speakers)
        if self.model_name == "v5_5_ru":
            return ["aidar", "baya", "kseniya", "xenia", "eugene", "random"]
        return [self.speaker]

    async def preload(self) -> None:
        await self._ensure_model()

    async def _ensure_model(self):
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is not None:
                return self._model
            started = time.perf_counter()
            model, torch_module, selected_device = await asyncio.to_thread(self._load_model_sync)
            self._model = model
            self._torch = torch_module
            self._selected_device = selected_device
            self._available_speakers = self._extract_speakers(model)
            self._validate_speaker(self.speaker)
            load_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "Silero TTS model loaded: tts_model_load_ms=%s device=%s model=%s speaker=%s sample_rate=%s",
                load_ms,
                selected_device,
                self.model_name,
                self.speaker,
                self.sample_rate,
            )
            if self.warmup_enabled and not self._warmed_up:
                warmup_started = time.perf_counter()
                await asyncio.to_thread(self._apply_tts_sync, "Привет.", self.speaker)
                self._warmed_up = True
                logger.info(
                    "Silero TTS model warmed up: tts_warmup_ms=%s device=%s model=%s speaker=%s sample_rate=%s",
                    int((time.perf_counter() - warmup_started) * 1000),
                    selected_device,
                    self.model_name,
                    self.speaker,
                    self.sample_rate,
                )
            return self._model

    def _load_model_sync(self):
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "Silero TTS requires torch. Install CPU PyTorch and silero before using VOICE_TTS_PROVIDER=silero."
            ) from exc
        if self.cpu_threads > 0:
            torch.set_num_threads(self.cpu_threads)
        selected_device = self._select_device(torch)
        if self._model_loader is not None:
            model = self._model_loader()
        else:
            self._configure_certifi_ca_bundle()
            try:
                model, _ = torch.hub.load(
                    repo_or_dir="snakers4/silero-models",
                    model="silero_tts",
                    language="ru",
                    speaker=self.model_name,
                    # The desktop backend has no interactive stdin. Without an
                    # explicit trust decision Torch Hub blocks startup waiting
                    # for a confirmation that cannot be entered by the user.
                    trust_repo=True,
                )
            except Exception as exc:
                message = str(exc)
                if "CERTIFICATE_VERIFY_FAILED" in message or "[SSL:" in message:
                    raise RuntimeError(
                        "Silero TTS model download failed because HTTPS certificate verification failed. "
                        "Check Windows date/time, update trusted root certificates, update certifi in the "
                        "virtual environment, and remove the incomplete torch hub cache before retrying."
                    ) from exc
                raise
        if hasattr(model, "to"):
            moved_model = model.to(selected_device)
            if moved_model is not None:
                model = moved_model
        return model, torch, selected_device

    def _configure_certifi_ca_bundle(self) -> None:
        if os.environ.get("SSL_CERT_FILE"):
            return
        try:
            import certifi
        except ImportError:
            return
        os.environ["SSL_CERT_FILE"] = certifi.where()

    def _select_device(self, torch_module) -> str:
        if self.requested_device == "cpu":
            return "cpu"
        cuda_available = bool(torch_module.cuda.is_available())
        if self.requested_device == "cuda":
            if not cuda_available:
                raise RuntimeError("VOICE_SILERO_DEVICE=cuda was requested, but CUDA is not available")
            return "cuda"
        return "cuda" if cuda_available else "cpu"

    def _extract_speakers(self, model) -> set[str] | None:
        for attr in ("speakers", "speaker_names"):
            speakers = getattr(model, attr, None)
            if speakers:
                return {str(item) for item in speakers}
        return None

    def _validate_speaker(self, speaker: str) -> None:
        if self._available_speakers is None or speaker in self._available_speakers:
            return
        logger.debug(
            "Unknown Silero speaker requested: speaker=%s available_speakers=%s",
            speaker,
            sorted(self._available_speakers),
        )
        raise RuntimeError(f"Unknown Silero speaker: {speaker}")

    def _apply_tts_sync(self, text: str, speaker: str):
        if self._model is None or self._torch is None:
            raise RuntimeError("Silero model is not loaded")
        with self._torch.inference_mode():
            return self._model.apply_tts(
                text=text,
                speaker=speaker,
                sample_rate=self.sample_rate,
            )

    async def _synthesize_wav_bytes(self, text: str, speaker: str) -> tuple[bytes, float, int]:
        await self._ensure_model()
        self._validate_speaker(speaker)
        started = time.perf_counter()
        async with self._infer_lock:
            waveform = await asyncio.wait_for(
                asyncio.to_thread(self._apply_tts_sync, text, speaker),
                timeout=self.timeout_seconds,
            )
        synthesis_ms = int((time.perf_counter() - started) * 1000)
        wav_bytes = waveform_to_wav_bytes(waveform, self.sample_rate)
        duration = wav_duration_seconds(wav_bytes)
        logger.info(
            "Silero TTS segment synthesized: provider=silero model=%s speaker=%s device=%s "
            "text_length=%s word_count=%s synthesis_ms=%s audio_duration_ms=%s RTF=%.3f audio_bytes=%s",
            self.model_name,
            speaker,
            self._selected_device,
            len(text),
            len(text.split()),
            synthesis_ms,
            int(duration * 1000),
            (synthesis_ms / 1000) / duration if duration else 0.0,
            len(wav_bytes),
        )
        return wav_bytes, duration, synthesis_ms

    async def stream(self, request: TTSRequest):
        text = " ".join(request.text.strip().split())
        if not text:
            raise ValueError("TTS text is empty")
        speaker = self.resolve_voice(request.language, request.voice)
        wav_bytes, _, _ = await self._synthesize_wav_bytes(text, speaker)
        yield AudioChunk(
            data=wav_bytes,
            format="wav",
            sequence=0,
            is_final=True,
            metadata={
                "sample_rate": self.sample_rate,
                "channels": 1,
                "sample_width": 2,
                "speaker": speaker,
                "model": self.model_name,
                "device": self._selected_device,
            },
        )

    async def synthesize(self, text: str, voice: str, output_path: Path) -> TTSResult:
        normalized = " ".join(text.strip().split())
        if not normalized:
            raise ValueError("TTS text is empty")
        speaker = self.resolve_voice("ru", voice)
        started = time.perf_counter()
        output_path = output_path.with_suffix(self.file_extension)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
        temp_path.unlink(missing_ok=True)
        try:
            wav_bytes, audio_duration_seconds, _ = await self._synthesize_wav_bytes(normalized, speaker)
            temp_path.write_bytes(wav_bytes)
            if wav_duration_seconds(temp_path.read_bytes()) <= 0:
                raise RuntimeError("Silero TTS returned zero-duration audio")
            temp_path.replace(output_path)
        except asyncio.CancelledError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception:
            temp_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            raise
        return TTSResult(
            audio_path=output_path,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="silero",
            voice=speaker,
            chunks_count=1,
            audio_duration_seconds=audio_duration_seconds,
        )


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
