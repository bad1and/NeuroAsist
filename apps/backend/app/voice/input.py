"""Ephemeral PCM input transport, ring buffer and VAD for live voice."""

from __future__ import annotations

import asyncio
import array
import contextlib
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import WebSocket

from apps.backend.app.voice.audio import (
    CANONICAL_FORMAT,
    CANONICAL_SAMPLE_RATE,
    Pcm16Audio,
    StreamingPcm16Normalizer,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VadObservation:
    value: float
    samples: int


class VadRuntimeError(RuntimeError):
    pass


class VadStream:
    name = "energy"
    scale = "rms"

    def feed(self, pcm16: bytes) -> list[VadObservation]:
        if len(pcm16) < 2:
            return []
        samples = memoryview(pcm16).cast("h")
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
        return [VadObservation(rms, len(samples))]

    def reset(self) -> None:
        return None


class VadProvider:
    name = "energy"
    scale = "rms"
    ready = True
    error: str | None = None

    def create_stream(self) -> VadStream:
        # Compatibility for third-party/test providers written against the
        # pre-streaming API. Production providers use an isolated VadStream.
        if type(self).probability is not VadProvider.probability:
            return _LegacyVadStream(self)
        return VadStream()

    def probability(self, pcm16: bytes, sample_rate: int) -> float:
        observations = VadStream().feed(pcm16)
        return observations[0].value if observations else 0.0


class _LegacyVadStream(VadStream):
    def __init__(self, provider: VadProvider) -> None:
        self._provider = provider
        self.name = provider.name
        self.scale = provider.scale

    def feed(self, pcm16: bytes) -> list[VadObservation]:
        return [
            VadObservation(
                float(self._provider.probability(pcm16, CANONICAL_SAMPLE_RATE)),
                len(pcm16) // 2,
            )
        ]


class SileroVadStream(VadStream):
    name = "silero"
    scale = "probability"
    window_samples = 512

    def __init__(self, model, torch_module) -> None:
        self._model = model
        self._torch = torch_module
        self._buffer = bytearray()
        self.reset()

    def feed(self, pcm16: bytes) -> list[VadObservation]:
        self._buffer.extend(pcm16)
        observations: list[VadObservation] = []
        window_bytes = self.window_samples * 2
        try:
            while len(self._buffer) >= window_bytes:
                window = bytes(self._buffer[:window_bytes])
                del self._buffer[:window_bytes]
                values = array.array("h")
                values.frombytes(window)
                audio = self._torch.tensor(values, dtype=self._torch.float32).div_(32768.0)
                with self._torch.inference_mode():
                    probability = float(self._model(audio, CANONICAL_SAMPLE_RATE).item())
                observations.append(
                    VadObservation(max(0.0, min(1.0, probability)), self.window_samples)
                )
        except Exception as exc:
            raise VadRuntimeError(f"Silero VAD inference failed: {type(exc).__name__}") from exc
        return observations

    def reset(self) -> None:
        self._buffer.clear()
        reset = getattr(self._model, "reset_states", None)
        if callable(reset):
            reset()


class SileroVadProvider(VadProvider):
    """Factory for session-isolated local Silero streaming runners."""

    name = "silero"
    scale = "probability"

    def __init__(self, model_path: Path | None) -> None:
        self._model_path = model_path if model_path and model_path.is_file() else None
        self._first_model = None
        self._torch = None
        self._package_loader = None
        self.model = "silero_vad"
        self.version: str | None = None
        self.error: str | None = None
        try:
            import torch

            self._torch = torch
            try:
                import silero_vad
                from silero_vad import load_silero_vad

                self.version = getattr(silero_vad, "__version__", "6.2.1")
                self._package_loader = load_silero_vad
            except ImportError:
                self._package_loader = None
            if self._model_path is not None:
                try:
                    self._first_model = self._load_path_model()
                    self.model = str(self._model_path)
                except Exception as override_error:
                    logger.warning(
                        "Silero VAD override failed; trying packaged model: path=%s error_type=%s",
                        self._model_path,
                        type(override_error).__name__,
                    )
                    self._model_path = None
            if self._first_model is None and self._package_loader is not None:
                self._first_model = self._load_package_model()
                self.model = "silero_vad"
            if self._first_model is None:
                raise RuntimeError("neither the override nor packaged Silero VAD model is available")
        except Exception as exc:
            # Loading is optional at runtime: VoiceInputSessionManager will
            # transparently create an energy stream and report the reason.
            self.error = f"Could not load Silero VAD: {type(exc).__name__}: {exc}"
            logger.warning(self.error)

    @property
    def ready(self) -> bool:
        # `_first_model` is deliberately consumed by the first session so it
        # gets an isolated streaming state.  Subsequent sessions load their
        # own instance from the same local source; consuming that warm model
        # must not make the provider look unavailable.
        return self._torch is not None and (
            self._first_model is not None
            or self._model_path is not None
            or self._package_loader is not None
        )

    def create_stream(self) -> VadStream:
        if not self.ready:
            raise VadRuntimeError(self.error or "Silero VAD is unavailable")
        model = self._first_model
        self._first_model = None
        try:
            if model is None:
                model = (
                    self._load_path_model()
                    if self._model_path is not None
                    else self._load_package_model()
                )
        except Exception as exc:
            raise VadRuntimeError(
                f"Could not create Silero VAD stream: {type(exc).__name__}"
            ) from exc
        return SileroVadStream(model, self._torch)

    def _load_path_model(self):
        model = self._torch.jit.load(str(self._model_path), map_location="cpu")
        model.eval()
        return model

    def _load_package_model(self):
        model = self._package_loader(onnx=False)
        model.eval()
        return model


@dataclass
class VadGate:
    threshold: float | None = None
    start_threshold: float = .55
    end_threshold: float = .35
    start_ms: int = 64
    end_ms: int = 480
    sample_rate: int = CANONICAL_SAMPLE_RATE
    state: str = "listening"
    candidate_samples: int = 0
    silence_samples: int = 0
    last_endpoint_silence_samples: int = 0
    _legacy_candidate_at: float | None = field(default=None, init=False, repr=False)
    _legacy_silence_at: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.threshold is not None:
            self.start_threshold = self.threshold
            self.end_threshold = self.threshold

    def feed(self, value: float, samples: int) -> str | None:
        if isinstance(samples, float):
            return self._feed_legacy(value, samples)
        above_start = value >= self.start_threshold
        below_end = value < self.end_threshold
        if self.state == "listening" and above_start:
            self.state = "candidate"
            self.candidate_samples = samples
            if self._milliseconds(self.candidate_samples) >= self.start_ms:
                self.state = "speech"
                return "speech_started"
        elif self.state == "candidate":
            if not above_start:
                self.state = "listening"
                self.candidate_samples = 0
            else:
                self.candidate_samples += samples
            if self.state == "candidate" and self._milliseconds(self.candidate_samples) >= self.start_ms:
                self.state = "speech"
                return "speech_started"
        elif self.state == "speech" and below_end:
            self.state = "end_pending"
            self.silence_samples = samples
        elif self.state == "end_pending":
            # The lower threshold is the hangover threshold. A frame that is
            # quieter than speech onset but still above it is ongoing speech,
            # not silence. Keeping the previous silent frames in that case
            # made a short dip in volume accumulate across a resumed phrase.
            if not below_end:
                self.state = "speech"
                self.silence_samples = 0
            elif below_end:
                self.silence_samples += samples
            if self.state == "end_pending" and self._milliseconds(self.silence_samples) >= self.end_ms:
                self.last_endpoint_silence_samples = self.silence_samples
                self.state = "listening"
                self.candidate_samples = 0
                self.silence_samples = 0
                return "speech_ended"
        return None

    def _feed_legacy(self, value: float, timestamp: float) -> str | None:
        if self.state == "listening" and value >= self.start_threshold:
            self.state = "candidate"
            self._legacy_candidate_at = timestamp
        elif self.state == "candidate":
            if value < self.start_threshold:
                self.state = "listening"
                self._legacy_candidate_at = None
            elif (
                timestamp
                - (self._legacy_candidate_at if self._legacy_candidate_at is not None else 0.0)
            ) * 1000 >= self.start_ms:
                self.state = "speech"
                return "speech_started"
        elif self.state == "speech" and value < self.end_threshold:
            self.state = "end_pending"
            self._legacy_silence_at = timestamp
        elif self.state == "end_pending":
            if value >= self.end_threshold:
                self.state = "speech"
                self._legacy_silence_at = None
            elif (
                timestamp
                - (self._legacy_silence_at if self._legacy_silence_at is not None else timestamp)
            ) * 1000 >= self.end_ms:
                self.state = "listening"
                self._legacy_candidate_at = None
                self._legacy_silence_at = None
                return "speech_ended"
        return None

    def reconfigure_for_energy(
        self,
        *,
        start_threshold: float,
        end_threshold: float,
        start_ms: int,
    ) -> None:
        self.start_threshold = start_threshold
        self.end_threshold = end_threshold
        self.start_ms = start_ms
        self.state = "listening"
        self.candidate_samples = 0
        self.silence_samples = 0

    def _milliseconds(self, samples: int) -> float:
        return samples * 1000 / self.sample_rate


@dataclass
class InputConnection:
    websocket: WebSocket
    version: int = 1
    mode: str = "hands_free"
    generation: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, payload: dict) -> None:
        async with self.lock:
            await self.websocket.send_json(payload)


@dataclass
class InputSession:
    session_id: str
    connection: InputConnection
    source_sample_rate: int = CANONICAL_SAMPLE_RATE
    sample_rate: int = CANONICAL_SAMPLE_RATE
    channels: int = 1
    language: str = "ru"
    gate: VadGate = field(default_factory=VadGate)
    normalizer: StreamingPcm16Normalizer | None = None
    vad_stream: VadStream | None = None
    vad_fallback_reason: str | None = None
    capture_profile: str = "balanced"
    capture_settings: dict = field(default_factory=dict)
    capture_constraints: dict = field(default_factory=dict)
    capture_supported_constraints: dict = field(default_factory=dict)
    ring: deque[bytes] = field(default_factory=deque)
    ring_bytes: int = 0
    utterance: bytearray | None = None
    pending_turn: bytearray = field(default_factory=bytearray)
    pending_candidate_id: int | None = None
    candidate_sequence: int = 0
    endpoint_task: asyncio.Task | None = None
    speech_confirmed: bool = False
    speech_confirmation_due_at: float = 0.0
    speech_confirmation_samples: int = 0
    finalizing: bool = False
    finalize_tasks: set[asyncio.Task] = field(default_factory=set)


UtteranceHandler = Callable[[str, Pcm16Audio, str, InputConnection], Awaitable[None]]
SpeechStartedHandler = Callable[[str], Awaitable[int | None]]
BargeInGuard = Callable[[str], bool]


class VoiceInputSessionManager:
    """Consumes binary PCM frames; raw input never leaves process memory by default."""

    def __init__(
        self,
        voice_service,
        on_utterance: UtteranceHandler,
        on_speech_started: SpeechStartedHandler | None = None,
        *,
        vad: VadProvider | None = None,
        silero_start_threshold: float = .55,
        silero_end_threshold: float = .35,
        energy_start_rms: float = .018,
        energy_end_rms: float = .012,
        silero_start_ms: int = 64,
        energy_start_ms: int = 120,
        pre_roll_ms: int = 500,
        post_roll_ms: int = 180,
        end_silence_ms: int = 480,
        live_end_silence_ms: int = 320,
        live_fallback_end_silence_ms: int = 650,
        max_utterance_seconds: int = 45,
        max_turn_silence_ms: int = 2500,
        barge_in_guard: BargeInGuard | None = None,
        barge_in_confirmation_ms: int = 180,
        turn_detector=None,
        event_publisher=None,
    ) -> None:
        self._voice_service = voice_service
        self._on_utterance = on_utterance
        self._on_speech_started = on_speech_started
        self._vad = vad or VadProvider()
        self._silero_start_threshold = max(0.05, min(.95, silero_start_threshold))
        self._silero_end_threshold = max(0.01, min(self._silero_start_threshold, silero_end_threshold))
        self._energy_start_rms = max(0.0001, min(1.0, energy_start_rms))
        self._energy_end_rms = max(0.0001, min(self._energy_start_rms, energy_end_rms))
        self._silero_start_ms = max(32, silero_start_ms)
        self._energy_start_ms = max(32, energy_start_ms)
        self._pre_roll_ms = pre_roll_ms
        self._post_roll_ms = max(0, post_roll_ms)
        self._end_silence_ms = max(100, end_silence_ms)
        self._live_end_silence_ms = max(100, live_end_silence_ms)
        self._live_fallback_end_silence_ms = max(100, live_fallback_end_silence_ms)
        self._max_utterance_seconds = max_utterance_seconds
        self._max_turn_silence_ms = max(100, max_turn_silence_ms)
        self._barge_in_guard = barge_in_guard
        self._barge_in_confirmation_ms = max(0, barge_in_confirmation_ms)
        self._turn_detector = turn_detector
        self._event_publisher = event_publisher or (lambda *_: None)
        self._sessions: dict[str, InputSession] = {}

    @property
    def vad_status(self) -> dict[str, object]:
        ready = bool(getattr(self._vad, "ready", True))
        return {
            "configured_provider": self._vad.name,
            "active_provider": self._vad.name if ready else "energy",
            "provider": self._vad.name if ready else "energy",
            "ready": ready,
            "fallback": not ready,
            "fallback_reason": getattr(self._vad, "error", None),
            "error": getattr(self._vad, "error", None),
            "sample_rate": CANONICAL_SAMPLE_RATE,
            "window_samples": 512 if self._vad.name == "silero" else None,
            "model": getattr(self._vad, "model", None),
            "version": getattr(self._vad, "version", None),
        }

    async def register(self, session_id: str, websocket: WebSocket, *, version: int = 1) -> InputConnection:
        connection = InputConnection(websocket, version=version)
        self._sessions[session_id] = InputSession(session_id, connection)
        return connection

    async def unregister(self, session_id: str, connection: InputConnection) -> None:
        session = self._sessions.get(session_id)
        if session is not None and session.connection is connection:
            await self.stop(session_id, finalize_active=True)
            self._sessions.pop(session_id, None)
            if session.endpoint_task is not None:
                session.endpoint_task.cancel()
            session.endpoint_task = None
            if session.vad_stream is not None:
                session.vad_stream.reset()
            session.vad_stream = None
            session.normalizer = None

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            await self.unregister(session_id, session.connection)

    async def stop(self, session_id: str, *, finalize_active: bool = True) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        if session.normalizer is not None:
            with contextlib.suppress(Exception):
                tail = session.normalizer.flush()
                if tail:
                    await self._feed_canonical(session, tail)
            session.normalizer = None
        if finalize_active and session.utterance is not None and session.speech_confirmed:
            audio = bytes(session.utterance)
            session.utterance = None
            session.candidate_sequence += 1
            candidate_id = session.candidate_sequence
            if session.connection.mode == "live_conversation":
                session.pending_turn = bytearray(audio)
                session.pending_candidate_id = candidate_id
            finalize_task = self._start_finalize_task(session, audio, candidate_id)
            # An explicit stop must not close the WebSocket before the final
            # confirmed utterance has been flushed through STT.
            await asyncio.gather(finalize_task, return_exceptions=True)
        if session.vad_stream is not None:
            session.vad_stream.reset()

    async def start(
        self,
        session_id: str,
        *,
        sample_rate: int,
        channels: int,
        language: str,
        mode: str = "hands_free",
        audio_format: str = CANONICAL_FORMAT,
        capture_profile: str = "balanced",
        capture_settings: dict | None = None,
        capture_constraints: dict | None = None,
        capture_supported_constraints: dict | None = None,
    ) -> None:
        session = self._sessions[session_id]
        if not 8_000 <= sample_rate <= 96_000 or channels != 1:
            raise ValueError("PCM input requires mono audio between 8 and 96 kHz")
        if audio_format != CANONICAL_FORMAT:
            raise ValueError("PCM input format must be pcm_s16le")
        session.source_sample_rate = sample_rate
        session.sample_rate = CANONICAL_SAMPLE_RATE
        session.channels, session.language = channels, language
        session.normalizer = StreamingPcm16Normalizer(sample_rate)
        session.capture_profile = capture_profile if capture_profile in {"headset", "balanced", "speakers"} else "balanced"
        session.capture_settings = dict(capture_settings or {})
        session.capture_constraints = dict(capture_constraints or {})
        session.capture_supported_constraints = dict(capture_supported_constraints or {})
        session.connection.mode = mode if mode in {"hands_free", "live_conversation"} else "hands_free"
        live = session.connection.mode == "live_conversation"
        semantic_ready = bool(self._turn_detector is not None and getattr(self._turn_detector, "ready", False))
        session.vad_fallback_reason = None
        try:
            session.vad_stream = self._vad.create_stream()
        except Exception as exc:
            session.vad_stream = VadProvider().create_stream()
            session.vad_fallback_reason = str(exc)
        silero_active = session.vad_stream.name == "silero"
        session.gate = VadGate(
            start_threshold=self._silero_start_threshold if silero_active else self._energy_start_rms,
            end_threshold=self._silero_end_threshold if silero_active else self._energy_end_rms,
            start_ms=self._silero_start_ms if silero_active else self._energy_start_ms,
            end_ms=(
                self._live_end_silence_ms
                if live and semantic_ready
                else self._live_fallback_end_silence_ms
                if live
                else self._end_silence_ms
            ),
        )
        session.ring.clear()
        session.ring_bytes = 0
        session.utterance = None
        session.pending_turn.clear()
        session.pending_candidate_id = None
        session.speech_confirmed = False
        session.speech_confirmation_due_at = 0.0
        session.speech_confirmation_samples = 0
        if session.endpoint_task is not None:
            session.endpoint_task.cancel()
            session.endpoint_task = None
        session.finalizing = False
        vad_status = self._session_vad_status(session)
        await session.connection.send({
            "type": "voice.input.ready",
            "source_sample_rate": sample_rate,
            "canonical_sample_rate": CANONICAL_SAMPLE_RATE,
            "sample_rate": CANONICAL_SAMPLE_RATE,
            "channels": 1,
            "format": CANONICAL_FORMAT,
            "resampled": sample_rate != CANONICAL_SAMPLE_RATE,
            "capture_profile": session.capture_profile,
            "capture_settings": session.capture_settings,
            "capture_constraints": session.capture_constraints,
            "capture_supported_constraints": session.capture_supported_constraints,
            "vad": vad_status,
            "turn_detector": {
                "provider": getattr(self._turn_detector, "name", "heuristic"),
                "ready": semantic_ready,
                "fallback": not semantic_ready,
                "error": getattr(self._turn_detector, "error", None),
            },
        })
        self._event_publisher(
            "voice.input.capture_configured",
            "info",
            "Voice input capture configured",
            {
                "session_id": session_id,
                "source_sample_rate": sample_rate,
                "canonical_sample_rate": CANONICAL_SAMPLE_RATE,
                "channels": 1,
                "format": CANONICAL_FORMAT,
                "profile": session.capture_profile,
                "track_settings": session.capture_settings,
                "constraints": session.capture_constraints,
                "supported_constraints": session.capture_supported_constraints,
                "vad": vad_status,
            },
        )
        if session.vad_fallback_reason:
            self._publish_vad_fallback(session, session.vad_fallback_reason)

    async def feed(self, session_id: str, pcm16: bytes) -> None:
        session = self._sessions.get(session_id)
        if session is None or not pcm16:
            return
        if len(pcm16) % 2:
            await session.connection.send({"type": "voice.input.error", "message": "PCM16 frame has an odd byte length"})
            return
        if session.normalizer is None:
            await session.connection.send({"type": "voice.input.error", "message": "PCM input session has not started"})
            return
        try:
            normalized = session.normalizer.feed(pcm16)
        except Exception as exc:
            await session.connection.send({"type": "voice.input.error", "message": str(exc)})
            return
        if normalized:
            await self._feed_canonical(session, normalized)

    async def _feed_canonical(self, session: InputSession, pcm16: bytes) -> None:
        self._append_ring(session, pcm16)
        now = time.monotonic()
        try:
            observations = session.vad_stream.feed(pcm16) if session.vad_stream is not None else []
        except VadRuntimeError as exc:
            await self._switch_to_energy(session, str(exc))
            observations = session.vad_stream.feed(pcm16)
        event = None
        for observation in observations:
            event = session.gate.feed(observation.value, observation.samples)
            if event is not None:
                break
        if event == "speech_started":
            session.utterance = bytearray(session.pending_turn)
            session.utterance.extend(bytearray().join(session.ring))
            guarded = bool(
                session.connection.mode == "live_conversation"
                and self._barge_in_guard is not None
                and self._barge_in_guard(session.session_id)
            )
            session.speech_confirmed = False
            session.speech_confirmation_samples = session.gate.candidate_samples
            session.speech_confirmation_due_at = (
                now + self._barge_in_confirmation_ms / 1000 if guarded else now
            )
            if not guarded:
                await self._confirm_speech_started(session)
        elif session.utterance is not None:
            session.utterance.extend(pcm16)
            if session.gate.state == "speech":
                session.speech_confirmation_samples += len(pcm16) // 2
            confirmation_by_samples = (
                session.speech_confirmation_samples * 1000 / CANONICAL_SAMPLE_RATE
                >= self._barge_in_confirmation_ms
            )
            legacy_confirmation = (
                isinstance(session.vad_stream, _LegacyVadStream)
                and now >= session.speech_confirmation_due_at
            )
            if (
                not session.speech_confirmed
                and session.gate.state == "speech"
                and (confirmation_by_samples or legacy_confirmation)
            ):
                await self._confirm_speech_started(session)
            if len(session.utterance) > session.sample_rate * 2 * self._max_utterance_seconds:
                event = "speech_ended"
        if event == "speech_ended" and session.utterance is not None:
            if not session.speech_confirmed:
                session.utterance = None
                session.speech_confirmation_due_at = 0.0
                session.speech_confirmation_samples = 0
                if session.connection.mode == "live_conversation":
                    await session.connection.send({
                        "type": "conversation.noise_ignored",
                        "reason": "barge_in_too_short",
                        "generation": session.connection.generation,
                    })
                return
            trim_samples = max(
                0,
                session.gate.last_endpoint_silence_samples
                - round(self._post_roll_ms * CANONICAL_SAMPLE_RATE / 1000),
            )
            trim_bytes = min(len(session.utterance), trim_samples * 2)
            audio = bytes(session.utterance[:-trim_bytes] if trim_bytes else session.utterance)
            session.utterance = None
            session.candidate_sequence += 1
            candidate_id = session.candidate_sequence
            # Retain the complete candidate before asynchronous endpoint
            # inference/STT begins. If speech resumes while either is running,
            # the next utterance is assembled from this audio instead of
            # silently losing the earlier speech island.
            if session.connection.mode == "live_conversation":
                session.pending_turn = bytearray(audio)
                session.pending_candidate_id = candidate_id
                session.ring.clear()
                session.ring_bytes = 0
            # Finalization is intentionally concurrent with continued PCM
            # ingestion. A new speech island can start while STT is running.
            self._start_finalize_task(session, audio, candidate_id)

    async def _confirm_speech_started(self, session: InputSession) -> None:
        if session.speech_confirmed or session.utterance is None:
            return
        if session.endpoint_task is not None:
            session.endpoint_task.cancel()
            session.endpoint_task = None
        session.pending_turn.clear()
        session.pending_candidate_id = None
        if self._on_speech_started is not None:
            generation = await self._on_speech_started(session.session_id)
            if generation is not None:
                session.connection.generation = generation
        session.speech_confirmed = True
        await session.connection.send({
            "type": "voice.input.speech_started",
            "generation": session.connection.generation,
            "vad": self._session_vad_status(session),
        })

    async def _switch_to_energy(self, session: InputSession, reason: str) -> None:
        if session.vad_stream is not None and session.vad_stream.name == "energy":
            return
        session.vad_stream = VadProvider().create_stream()
        session.vad_fallback_reason = reason
        session.gate.reconfigure_for_energy(
            start_threshold=self._energy_start_rms,
            end_threshold=self._energy_end_rms,
            start_ms=self._energy_start_ms,
        )
        payload = {
            "type": "voice.input.vad_changed",
            "vad": self._session_vad_status(session),
            "reason": reason,
        }
        await session.connection.send(payload)
        self._publish_vad_fallback(session, reason)

    def _publish_vad_fallback(self, session: InputSession, reason: str) -> None:
        logger.warning(
            "Voice VAD switched to energy fallback: session_id=%s reason=%s",
            session.session_id,
            reason,
        )
        self._event_publisher(
            "voice.vad_fallback",
            "warning",
            "Silero VAD unavailable; energy fallback is active",
            {
                "session_id": session.session_id,
                "configured_provider": self._vad.name,
                "active_provider": "energy",
                "reason": reason,
            },
        )

    def _session_vad_status(self, session: InputSession) -> dict[str, object]:
        active = session.vad_stream.name if session.vad_stream is not None else "energy"
        return {
            "configured_provider": self._vad.name,
            "active_provider": active,
            "provider": active,
            "ready": active == self._vad.name,
            "fallback": active != self._vad.name,
            "fallback_reason": session.vad_fallback_reason,
            "error": session.vad_fallback_reason,
            "sample_rate": CANONICAL_SAMPLE_RATE,
            "window_samples": 512 if active == "silero" else None,
            "scale": session.vad_stream.scale if session.vad_stream is not None else "rms",
            "model": getattr(self._vad, "model", None),
            "version": getattr(self._vad, "version", None),
        }

    def _start_finalize_task(
        self,
        session: InputSession,
        audio: bytes,
        candidate_id: int,
    ) -> asyncio.Task:
        session.finalizing = True
        task = asyncio.create_task(
            self._finalize(
                session,
                audio,
                session.connection.generation,
                candidate_id,
                time.monotonic(),
            ),
            name=f"voice-input-{session.session_id}-{session.connection.generation}",
        )
        session.finalize_tasks.add(task)
        task.add_done_callback(session.finalize_tasks.discard)
        return task

    def _append_ring(self, session: InputSession, pcm16: bytes) -> None:
        max_bytes = int(session.sample_rate * 2 * self._pre_roll_ms / 1000)
        if max_bytes <= 0:
            session.ring.clear()
            session.ring_bytes = 0
            return
        # The browser normally sends 20 ms frames, but an initial WebSocket
        # backlog or a delayed AudioWorklet may yield one frame larger than the
        # whole pre-roll window. Dropping that complete frame loses the start
        # of the first spoken word exactly when VAD confirms speech.
        if len(pcm16) >= max_bytes:
            tail = pcm16[-max_bytes:]
            session.ring.clear()
            session.ring.append(tail)
            session.ring_bytes = len(tail)
            return
        session.ring.append(pcm16)
        session.ring_bytes += len(pcm16)
        while session.ring and session.ring_bytes > max_bytes:
            session.ring_bytes -= len(session.ring.popleft())

    async def _finalize(
        self,
        session: InputSession,
        pcm16: bytes,
        generation: int,
        candidate_id: int,
        boundary_at: float,
    ) -> None:
        close_candidate = False
        connection = InputConnection(
            session.connection.websocket,
            version=session.connection.version,
            mode=session.connection.mode,
            generation=generation,
            lock=session.connection.lock,
        )
        try:
            if connection.mode == "live_conversation" and self._turn_detector is not None:
                await connection.send({
                    "type": "conversation.turn_candidate",
                    "generation": generation,
                })
                detection = await self._turn_detector.analyze(pcm16, session.sample_rate)
                if not self._candidate_is_current(session, generation, candidate_id):
                    return
                await connection.send({
                    "type": "conversation.turn_completed" if detection.complete else "conversation.phase",
                    "generation": generation,
                    "complete": detection.complete,
                    "confidence": detection.confidence,
                    "provider": detection.provider,
                    "latency_ms": round(detection.latency_ms, 2),
                    "fallback": detection.fallback,
                    "phase": "transcribing" if detection.complete else "endpoint_pending",
                })
                if not detection.complete:
                    self._schedule_forced_endpoint(
                        session,
                        connection,
                        pcm16,
                        generation,
                        candidate_id,
                        boundary_at,
                    )
                    return
            close_candidate = True
            with contextlib.suppress(Exception):
                await connection.send({"type": "voice.input.finalizing", "generation": generation})
            await self._deliver_utterance(session, pcm16, connection)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await connection.send({"type": "voice.input.error", "message": str(exc)})
        finally:
            if close_candidate and self._candidate_is_current(session, generation, candidate_id):
                session.pending_turn.clear()
                session.pending_candidate_id = None
            session.finalizing = False

    def _candidate_is_current(
        self,
        session: InputSession,
        generation: int,
        candidate_id: int,
    ) -> bool:
        return (
            generation == session.connection.generation
            and session.pending_candidate_id == candidate_id
        )

    def _schedule_forced_endpoint(
        self,
        session: InputSession,
        connection: InputConnection,
        pcm16: bytes,
        generation: int,
        candidate_id: int,
        boundary_at: float,
    ) -> None:
        if session.endpoint_task is not None:
            session.endpoint_task.cancel()
        elapsed = max(0.0, time.monotonic() - boundary_at)
        delay = max(0.0, self._max_turn_silence_ms / 1000 - elapsed)
        task = asyncio.create_task(
            self._force_endpoint(
                session,
                connection,
                pcm16,
                generation,
                candidate_id,
                delay,
            ),
            name=f"voice-endpoint-{session.session_id}-{generation}",
        )
        session.endpoint_task = task
        task.add_done_callback(
            lambda completed: self._clear_endpoint_task(session, completed)
        )

    async def _force_endpoint(
        self,
        session: InputSession,
        connection: InputConnection,
        pcm16: bytes,
        generation: int,
        candidate_id: int,
        delay: float,
    ) -> None:
        await asyncio.sleep(delay)
        if not self._candidate_is_current(session, generation, candidate_id):
            return
        await connection.send({
            "type": "conversation.turn_completed",
            "generation": generation,
            "complete": True,
            "confidence": 0.5,
            "provider": "forced-timeout",
            "latency_ms": round(self._max_turn_silence_ms, 2),
            "fallback": True,
            "phase": "transcribing",
        })
        try:
            await connection.send({"type": "voice.input.finalizing", "generation": generation})
            await self._deliver_utterance(session, pcm16, connection)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await connection.send({"type": "voice.input.error", "message": str(exc)})
        finally:
            if self._candidate_is_current(session, generation, candidate_id):
                session.pending_turn.clear()
                session.pending_candidate_id = None

    @staticmethod
    def _clear_endpoint_task(session: InputSession, task: asyncio.Task) -> None:
        if session.endpoint_task is task:
            session.endpoint_task = None

    async def _deliver_utterance(
        self,
        session: InputSession,
        pcm16: bytes,
        connection: InputConnection,
    ) -> None:
        if hasattr(self._voice_service, "transcribe_pcm16"):
            await self._on_utterance(
                session.session_id,
                Pcm16Audio(pcm16),
                session.language,
                connection,
            )
            return
        # Compatibility for integrations that still expose the old temporary
        # file callback. The production VoiceService always takes the branch
        # above and never writes live audio to disk.
        path = self._voice_service.save_pcm16_temp(pcm16, CANONICAL_SAMPLE_RATE)
        try:
            await self._on_utterance(session.session_id, path, session.language, connection)
        finally:
            self._voice_service.cleanup_upload(path)
