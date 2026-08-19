"""TeraTTSv2 production provider.

The model is intentionally imported only when the provider is preloaded or the
first utterance arrives.  This keeps text-only startup and test environments
free from the heavyweight ONNX/Transformers import cost.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import logging
import time
from pathlib import Path
from typing import Any, Callable

from apps.backend.app.voice.delivery import MAX_SPEECH_TEMPO, MIN_SPEECH_TEMPO
from apps.backend.app.voice.providers import (
    AudioChunk,
    TTSProvider,
    TTSRequest,
    TTSResult,
    apply_wav_delivery,
    waveform_to_wav_bytes,
    wav_duration_seconds,
)
from apps.backend.app.voice.style import (
    VoiceExpressionLevel,
    VoiceStyle,
    coerce_voice_expression_level,
    coerce_voice_style,
)
from apps.backend.app.voice.teratts_normalizer import normalize_for_teratts

logger = logging.getLogger(__name__)

TERATTS_MODEL_ID = "TeraSpace/TeraTTSv2"
TERATTS_REVISION = "f05ea799094571a3553904a555df3834fb0b963b"
TERATTS_SAMPLE_RATE = 44_100
TERATTS_VOICES = (
    "eng_f3", "eng_f4_whisper", "eng_f5", "eng_m2_whisper", "eng_m3", "eng_m4",
    "ru_f1", "ru_f2", "ru_m1", "ru_m5",
)

_STYLE_SCALE = {
    VoiceStyle.AUTO: 1.00,
    VoiceStyle.NORMAL: 1.00,
    VoiceStyle.CALM: 1.18,
    VoiceStyle.THOUGHTFUL: 1.15,
    VoiceStyle.ENERGETIC: 0.88,
    VoiceStyle.ASSERTIVE: 0.90,
}
_EXPRESSION_STRENGTH = {
    VoiceExpressionLevel.MINIMAL: 0.45,
    VoiceExpressionLevel.NATURAL: 1.0,
    VoiceExpressionLevel.NOTICEABLE: 1.6,
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


class TeraTTSProvider(TTSProvider):
    """Lazy, deterministic TeraTTSv2 provider with a stable WAV contract."""

    def __init__(
        self,
        *,
        model_id: str = TERATTS_MODEL_ID,
        revision: str = TERATTS_REVISION,
        model_path: Path | None = None,
        cache_dir: Path | None = None,
        voice: str = "ru_f1",
        device: str = "cpu",
        threads: int = 8,
        diffusion_model: str = "distilled",
        ruaccent_mode: str = "full",
        russian_stress: bool = True,
        chunk_frames: int = 16,
        seed: int = 1234,
        warmup: bool = True,
        timeout_seconds: float = 45.0,
        audio_postprocessing_enabled: bool = True,
        loudness_target_dbfs: float = -18.0,
        peak_ceiling_dbfs: float = -1.0,
        highpass_cutoff_hz: float = 60.0,
        pronunciation_dictionary_path: Path | None = None,
        model_loader: Callable[..., Any] | None = None,
    ) -> None:
        if device not in {"cpu", "auto"}:
            raise ValueError("TeraTTS currently supports CPU or auto execution only")
        if diffusion_model not in {"distilled", "teacher"}:
            raise ValueError("TeraTTS diffusion model must be distilled or teacher")
        if voice not in TERATTS_VOICES:
            raise ValueError(f"Unknown TeraTTS voice: {voice}")
        self.model_id = model_id
        self.revision = revision
        self.model_path = model_path.expanduser() if model_path else None
        self.cache_dir = cache_dir.expanduser() if cache_dir else None
        self.voice = voice
        self.requested_device = device
        self.threads = max(1, int(threads))
        self.diffusion_model = diffusion_model
        self.ruaccent_mode = ruaccent_mode
        self.russian_stress = bool(russian_stress)
        self.chunk_frames = max(1, int(chunk_frames))
        self.seed = int(seed)
        self.warmup_enabled = bool(warmup)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.audio_postprocessing_enabled = bool(audio_postprocessing_enabled)
        self.loudness_target_dbfs = float(loudness_target_dbfs)
        self.peak_ceiling_dbfs = float(peak_ceiling_dbfs)
        self.highpass_cutoff_hz = max(0.0, float(highpass_cutoff_hz))
        self.pronunciation_dictionary_path = pronunciation_dictionary_path
        self._model_loader = model_loader
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()
        self._infer_lock = asyncio.Lock()
        self._pronunciations: dict[str, str] = {}
        self._expression_level = VoiceExpressionLevel.NATURAL
        self._selected_device = "cpu"
        self._warmed_up = False
        self._last_load_ms: int | None = None
        self._last_error: str | None = None

    @property
    def name(self) -> str:
        return "teratts"

    @property
    def output_format(self) -> str:
        return "wav"

    @property
    def available_speakers(self) -> list[str]:
        voices = list(TERATTS_VOICES)
        if self.voice in voices:
            voices.remove(self.voice)
            voices.insert(0, self.voice)
        return voices

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model_id,
            "revision": self.revision,
            "voice": self.voice,
            "device": self._selected_device,
            "sample_rate": TERATTS_SAMPLE_RATE,
            "channels": 1,
            "sample_width": 2,
            "diffusion_model": self.diffusion_model,
            "ruaccent_mode": self.ruaccent_mode,
            "russian_stress": self.russian_stress,
            "seed": self.seed,
            "chunk_frames": self.chunk_frames,
            "warm": self._warmed_up,
            "loaded": self._model is not None,
            "load_ms": self._last_load_ms,
            "error": self._last_error,
            "native_stream": True,
        }

    def resolve_voice(self, language: str, requested_voice: str | None = None) -> str:
        if requested_voice in TERATTS_VOICES:
            return str(requested_voice)
        if str(language).lower().startswith("en"):
            return "eng_f4_whisper"
        return self.voice

    def set_pronunciations(self, pronunciations: dict[str, str]) -> None:
        self._pronunciations = {
            str(source).strip(): str(target).strip()
            for source, target in pronunciations.items()
            if str(source).strip() and str(target).strip()
        }

    def set_expression_level(self, level: str | VoiceExpressionLevel) -> None:
        self._expression_level = coerce_voice_expression_level(level)

    async def preload(self) -> None:
        await self._ensure_model()

    async def close(self) -> None:
        """Stop inference and release the remote-code/ONNX model resources."""
        async with self._load_lock:
            async with self._infer_lock:
                model = self._model
                self._model = None
                self._warmed_up = False
                if model is not None:
                    await asyncio.to_thread(self._close_model_sync, model)

    @staticmethod
    def _close_model_sync(model: Any) -> None:
        for method_name in ("close", "shutdown", "release"):
            method = getattr(model, method_name, None)
            if callable(method):
                with contextlib.suppress(Exception):
                    method()
                break
        del model
        gc.collect()

    async def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is not None:
                return self._model
            started = time.perf_counter()
            try:
                self._model = await asyncio.to_thread(self._load_model_sync)
                self._last_load_ms = int((time.perf_counter() - started) * 1000)
                self._last_error = None
                logger.info(
                    "TeraTTS model loaded: model=%s revision=%s load_ms=%s cache=%s",
                    self.model_id, self.revision, self._last_load_ms,
                    self.model_path or self.cache_dir or "huggingface-default",
                )
                if self.warmup_enabled and not self._warmed_up:
                    await asyncio.to_thread(self._warmup_sync)
                    self._warmed_up = True
                return self._model
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._model = None
                raise self._friendly_load_error(exc) from exc

    def _load_model_sync(self) -> Any:
        if self.model_path is not None and not self.model_path.is_dir():
            raise RuntimeError(f"TeraTTS local model directory does not exist: {self.model_path}")
        if self._model_loader is not None:
            kwargs = {
                "model_id": self.model_id,
                "revision": self.revision,
                "model_path": self.model_path,
                "cache_dir": self.cache_dir,
                "provider": "CPUExecutionProvider",
                "threads": self.threads,
                "diffusion_model": self.diffusion_model,
                "ruaccent_mode": self.ruaccent_mode,
                "russian_stress": self.russian_stress,
            }
            try:
                return self._model_loader(**kwargs)
            except TypeError as exc:
                # Small fakes and dependency-injection adapters often expose a
                # zero-argument loader. Preserve that useful test seam without
                # changing the production AutoModel path.
                if "unexpected keyword" not in str(exc) and "positional argument" not in str(exc):
                    raise
                return self._model_loader()
        try:
            from transformers import AutoModel
        except ImportError as exc:
            raise RuntimeError(
                "TeraTTS requires transformers, huggingface_hub, onnxruntime and num2words"
            ) from exc
        source = str(self.model_path) if self.model_path else self.model_id
        kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "provider": "CPUExecutionProvider",
            "threads": self.threads,
            "diffusion_model": self.diffusion_model,
            "ruaccent_mode": self.ruaccent_mode,
            "russian_stress": self.russian_stress,
        }
        if self.model_path:
            kwargs["local_files_only"] = True
        else:
            kwargs["revision"] = self.revision
            if self.cache_dir:
                kwargs["cache_dir"] = str(self.cache_dir)
        return AutoModel.from_pretrained(source, **kwargs)

    def _warmup_sync(self) -> None:
        self._render_sync("Привет.", self.voice, VoiceStyle.NORMAL, 1.0)

    @staticmethod
    def _friendly_load_error(exc: Exception) -> RuntimeError:
        message = str(exc)
        lowered = message.lower()
        if any(marker in lowered for marker in (
            "connection", "offline", "couldn't connect", "local_files_only",
            "localentrynotfounderror", "not found", "could not find",
        )):
            return RuntimeError(
                "TeraTTS model is not cached and Hugging Face is unavailable. "
                "Connect once or set VOICE_TERATTS_MODEL_PATH to a local model directory."
            )
        if any(marker in lowered for marker in ("vocab.txt", "encoding", "unicode", "charmap", "decode")):
            return RuntimeError(
                "TeraTTS could not read its Russian accent assets. Restart the desktop launcher "
                "with PYTHONUTF8=1 and PYTHONIOENCODING=utf-8."
            )
        return RuntimeError(f"TeraTTS model load failed: {message}")

    def _duration_scale(self, request: TTSRequest) -> float:
        style = coerce_voice_style(request.style)
        base = _STYLE_SCALE[style]
        strength = _EXPRESSION_STRENGTH[self._expression_level]
        base = 1.0 + (base - 1.0) * strength
        tempo = _clamp(request.tempo, MIN_SPEECH_TEMPO, MAX_SPEECH_TEMPO)
        # ``tempo > 1`` means faster in the existing delivery contract;
        # TeraTTS uses the inverse convention: larger duration_scale is slower.
        return _clamp(base / tempo, 0.75, 1.30)

    def _render_sync(
        self,
        text: str,
        voice: str,
        style: VoiceStyle | str,
        tempo: float,
    ) -> tuple[bytes, str, float]:
        if self._model is None:
            raise RuntimeError("TeraTTS model is not loaded")
        import numpy as np

        normalized = normalize_for_teratts(text, self._pronunciations)
        duration_scale = self._duration_scale(
            TTSRequest(text=text, language="ru", voice=voice, style=style, tempo=tempo)
        )
        stream_method = getattr(self._model, "generate_speech_stream", None)
        if callable(stream_method):
            chunks = stream_method(
                normalized,
                voice=voice,
                duration_scale=duration_scale,
                seed=self.seed,
                chunk_frames=self.chunk_frames,
            )
            arrays = [
                np.asarray(chunk, dtype=np.float32).reshape(-1)
                for chunk in chunks
                if np.asarray(chunk).size
            ]
            if not arrays:
                raise RuntimeError("TeraTTS returned empty audio stream")
            waveform = np.concatenate(arrays)
        else:
            generate = getattr(self._model, "generate_speech", None)
            if not callable(generate):
                raise RuntimeError("TeraTTS model does not expose speech generation")
            waveform = np.asarray(
                generate(normalized, voice=voice, duration_scale=duration_scale, seed=self.seed),
                dtype=np.float32,
            ).reshape(-1)
        waveform = np.nan_to_num(waveform, nan=0.0, posinf=1.0, neginf=-1.0)
        if waveform.size == 0:
            raise RuntimeError("TeraTTS returned empty audio")
        return waveform_to_wav_bytes(waveform, TERATTS_SAMPLE_RATE), normalized, duration_scale

    async def _synthesize_request(self, request: TTSRequest) -> tuple[bytes, dict[str, Any]]:
        text = " ".join(request.text.strip().split())
        if not text:
            raise ValueError("TTS text is empty")
        voice = self.resolve_voice(request.language, request.voice)
        await self._ensure_model()
        started = time.perf_counter()
        async with self._infer_lock:
            wav_bytes, normalized, duration_scale = await asyncio.wait_for(
                asyncio.to_thread(self._render_sync, text, voice, request.style, request.tempo),
                timeout=self.timeout_seconds,
            )
        synthesis_ms = int((time.perf_counter() - started) * 1000)
        delivery_started = time.perf_counter()
        wav_bytes = await asyncio.to_thread(
            apply_wav_delivery,
            wav_bytes,
            tempo=1.0,
            pause_before_ms=request.pause_before_ms,
            pause_after_ms=request.pause_after_ms,
            postprocess=self.audio_postprocessing_enabled,
            loudness_target_dbfs=self.loudness_target_dbfs,
            peak_ceiling_dbfs=self.peak_ceiling_dbfs,
            highpass_cutoff_hz=self.highpass_cutoff_hz,
        )
        duration = await asyncio.to_thread(wav_duration_seconds, wav_bytes)
        metadata = {
            "provider": self.name,
            "model": self.model_id,
            "revision": self.revision,
            "voice": voice,
            "device": self._selected_device,
            "sample_rate": TERATTS_SAMPLE_RATE,
            "channels": 1,
            "sample_width": 2,
            "style": coerce_voice_style(request.style).value,
            "tempo": _clamp(request.tempo, MIN_SPEECH_TEMPO, MAX_SPEECH_TEMPO),
            "duration_scale": duration_scale,
            "seed": self.seed,
            "normalized_text": normalized,
            "synthesis_ms": synthesis_ms,
            "tempo_processing_ms": int((time.perf_counter() - delivery_started) * 1000),
            "rtf": (synthesis_ms / 1000.0) / duration if duration else None,
            "native_stream": True,
        }
        return wav_bytes, metadata

    async def stream(self, request: TTSRequest):
        wav_bytes, metadata = await self._synthesize_request(request)
        yield AudioChunk(wav_bytes, "wav", 0, is_final=True, metadata=metadata)

    async def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        style: VoiceStyle | str = VoiceStyle.AUTO,
    ) -> TTSResult:
        started = time.perf_counter()
        request = TTSRequest(text=text, language="ru", voice=voice, style=style)
        chunks = [chunk async for chunk in self.stream(request)]
        if not chunks:
            raise RuntimeError("TeraTTS returned no audio chunks")
        output_path = output_path.with_suffix(".wav")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
        temp_path.unlink(missing_ok=True)
        try:
            temp_path.write_bytes(chunks[-1].data)
            duration = wav_duration_seconds(temp_path.read_bytes())
            temp_path.replace(output_path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
        return TTSResult(
            audio_path=output_path,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider=self.name,
            voice=self.resolve_voice("ru", voice),
            chunks_count=len(chunks),
            audio_duration_seconds=duration,
        )
