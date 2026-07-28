"""Ephemeral PCM input transport, ring buffer and VAD for live voice."""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import WebSocket


class VadProvider:
    name = "energy"

    def probability(self, pcm16: bytes, sample_rate: int) -> float:
        if len(pcm16) < 2:
            return 0.0
        samples = memoryview(pcm16).cast("h")
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
        return min(1.0, rms / .08)


class SileroVadProvider(VadProvider):
    """Local TorchScript Silero VAD. Missing/unreadable models safely fall back."""

    name = "silero"

    def __init__(self, model_path: Path | None) -> None:
        self._model = None
        self.error: str | None = None
        if model_path is None or not model_path.is_file():
            self.error = "Silero VAD model is not installed"
            return
        try:
            import torch
            self._torch = torch
            self._model = torch.jit.load(str(model_path), map_location="cpu")
            self._model.eval()
            self._buffer = bytearray()
            self._last_probability = 0.0
        except Exception as exc:  # optional runtime/model, never block voice
            self.error = f"Could not load Silero VAD: {exc}"

    @property
    def ready(self) -> bool:
        return self._model is not None

    def probability(self, pcm16: bytes, sample_rate: int) -> float:
        if self._model is None or sample_rate != 16000:
            return super().probability(pcm16, sample_rate)
        try:
            self._buffer.extend(pcm16)
            # Silero's 16 kHz JIT model consumes 512 samples (32 ms) at once;
            # AudioWorklet commonly produces smaller 128-sample callbacks.
            if len(self._buffer) < 1024:
                return self._last_probability or super().probability(pcm16, sample_rate)
            window = bytes(self._buffer[:1024])
            del self._buffer[:1024]
            samples = memoryview(window).cast("h")
            audio = self._torch.tensor([sample / 32768 for sample in samples], dtype=self._torch.float32)
            with self._torch.no_grad():
                value = self._model(audio, sample_rate)
            self._last_probability = max(0.0, min(1.0, float(value.item())))
            return self._last_probability
        except Exception:
            return super().probability(pcm16, sample_rate)


@dataclass
class VadGate:
    threshold: float = .55
    start_ms: int = 120
    end_ms: int = 650
    state: str = "listening"
    since: float = field(default_factory=time.monotonic)

    def feed(self, probability: float, now: float) -> str | None:
        speech = probability >= self.threshold
        if self.state == "listening" and speech:
            self.state, self.since = "candidate", now
        elif self.state == "candidate":
            if not speech:
                self.state = "listening"
            elif (now - self.since) * 1000 >= self.start_ms:
                self.state = "speech"
                return "speech_started"
        elif self.state == "speech" and not speech:
            self.state, self.since = "end_pending", now
        elif self.state == "end_pending":
            if speech:
                self.state = "speech"
            elif (now - self.since) * 1000 >= self.end_ms:
                self.state = "listening"
                return "speech_ended"
        return None


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
    sample_rate: int = 16000
    channels: int = 1
    language: str = "ru"
    gate: VadGate = field(default_factory=VadGate)
    ring: deque[bytes] = field(default_factory=deque)
    ring_bytes: int = 0
    utterance: bytearray | None = None
    pending_turn: bytearray = field(default_factory=bytearray)
    pending_candidate_id: int | None = None
    candidate_sequence: int = 0
    endpoint_task: asyncio.Task | None = None
    speech_confirmed: bool = False
    speech_confirmation_due_at: float = 0.0
    finalizing: bool = False
    finalize_tasks: set[asyncio.Task] = field(default_factory=set)


UtteranceHandler = Callable[[str, Path, str, InputConnection], Awaitable[None]]
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
        vad_threshold: float = .55,
        pre_roll_ms: int = 500,
        max_utterance_seconds: int = 45,
        max_turn_silence_ms: int = 2500,
        barge_in_guard: BargeInGuard | None = None,
        barge_in_confirmation_ms: int = 180,
        turn_detector=None,
    ) -> None:
        self._voice_service = voice_service
        self._on_utterance = on_utterance
        self._on_speech_started = on_speech_started
        self._vad = vad or VadProvider()
        self._vad_threshold = max(0.05, min(.95, vad_threshold))
        self._pre_roll_ms = pre_roll_ms
        self._max_utterance_seconds = max_utterance_seconds
        self._max_turn_silence_ms = max(100, max_turn_silence_ms)
        self._barge_in_guard = barge_in_guard
        self._barge_in_confirmation_ms = max(0, barge_in_confirmation_ms)
        self._turn_detector = turn_detector
        self._sessions: dict[str, InputSession] = {}

    @property
    def vad_status(self) -> dict[str, object]:
        return {"provider": self._vad.name, "ready": getattr(self._vad, "ready", True), "error": getattr(self._vad, "error", None)}

    async def register(self, session_id: str, websocket: WebSocket, *, version: int = 1) -> InputConnection:
        connection = InputConnection(websocket, version=version)
        self._sessions[session_id] = InputSession(session_id, connection)
        return connection

    async def unregister(self, session_id: str, connection: InputConnection) -> None:
        session = self._sessions.get(session_id)
        if session is not None and session.connection is connection:
            self._sessions.pop(session_id, None)
            if session.endpoint_task is not None:
                session.endpoint_task.cancel()
            for task in tuple(session.finalize_tasks):
                task.cancel()
            tasks = [*session.finalize_tasks]
            if session.endpoint_task is not None:
                tasks.append(session.endpoint_task)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            session.finalize_tasks.clear()
            session.endpoint_task = None

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            await self.unregister(session_id, session.connection)

    async def start(
        self,
        session_id: str,
        *,
        sample_rate: int,
        channels: int,
        language: str,
        mode: str = "hands_free",
    ) -> None:
        session = self._sessions[session_id]
        if sample_rate not in {8000, 16000, 24000, 48000} or channels != 1:
            raise ValueError("PCM input requires mono 8/16/24/48 kHz audio")
        session.sample_rate, session.channels, session.language = sample_rate, channels, language
        session.connection.mode = mode if mode in {"hands_free", "live_conversation"} else "hands_free"
        live = session.connection.mode == "live_conversation"
        semantic_ready = bool(self._turn_detector is not None and getattr(self._turn_detector, "ready", False))
        session.gate = VadGate(
            threshold=self._vad_threshold,
            end_ms=250 if live and semantic_ready else (750 if live else 650),
        )
        session.ring.clear()
        session.ring_bytes = 0
        session.utterance = None
        session.pending_turn.clear()
        session.pending_candidate_id = None
        session.speech_confirmed = False
        session.speech_confirmation_due_at = 0.0
        if session.endpoint_task is not None:
            session.endpoint_task.cancel()
            session.endpoint_task = None
        session.finalizing = False
        await session.connection.send({
            "type": "voice.input.ready",
            "sample_rate": sample_rate,
            "vad": self.vad_status,
            "turn_detector": {
                "provider": getattr(self._turn_detector, "name", "heuristic"),
                "ready": semantic_ready,
                "fallback": not semantic_ready,
                "error": getattr(self._turn_detector, "error", None),
            },
        })

    async def feed(self, session_id: str, pcm16: bytes) -> None:
        session = self._sessions.get(session_id)
        if session is None or not pcm16:
            return
        if len(pcm16) % 2:
            await session.connection.send({"type": "voice.input.error", "message": "PCM16 frame has an odd byte length"})
            return
        self._append_ring(session, pcm16)
        now = time.monotonic()
        event = session.gate.feed(self._vad.probability(pcm16, session.sample_rate), now)
        if event == "speech_started":
            session.utterance = bytearray(session.pending_turn)
            session.utterance.extend(bytearray().join(session.ring))
            guarded = bool(
                session.connection.mode == "live_conversation"
                and self._barge_in_guard is not None
                and self._barge_in_guard(session_id)
            )
            session.speech_confirmed = False
            session.speech_confirmation_due_at = (
                now + self._barge_in_confirmation_ms / 1000 if guarded else now
            )
            if not guarded:
                await self._confirm_speech_started(session)
        elif session.utterance is not None:
            session.utterance.extend(pcm16)
            if (
                not session.speech_confirmed
                and session.gate.state == "speech"
                and now >= session.speech_confirmation_due_at
            ):
                await self._confirm_speech_started(session)
            if len(session.utterance) > session.sample_rate * 2 * self._max_utterance_seconds:
                event = "speech_ended"
        if event == "speech_ended" and session.utterance is not None:
            if not session.speech_confirmed:
                session.utterance = None
                session.speech_confirmation_due_at = 0.0
                if session.connection.mode == "live_conversation":
                    await session.connection.send({
                        "type": "conversation.noise_ignored",
                        "reason": "barge_in_too_short",
                        "generation": session.connection.generation,
                    })
                return
            audio = bytes(session.utterance)
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
            session.finalizing = True
            task = asyncio.create_task(
                self._finalize(
                    session,
                    audio,
                    session.connection.generation,
                    candidate_id,
                    time.monotonic(),
                ),
                name=f"voice-input-{session_id}-{session.connection.generation}",
            )
            session.finalize_tasks.add(task)
            task.add_done_callback(session.finalize_tasks.discard)

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
        })

    def _append_ring(self, session: InputSession, pcm16: bytes) -> None:
        session.ring.append(pcm16)
        session.ring_bytes += len(pcm16)
        max_bytes = int(session.sample_rate * 2 * self._pre_roll_ms / 1000)
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
        path: Path | None = None
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
            await connection.send({"type": "voice.input.finalizing", "generation": generation})
            path = self._voice_service.save_pcm16_temp(pcm16, session.sample_rate)
            await self._on_utterance(session.session_id, path, session.language, connection)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await connection.send({"type": "voice.input.error", "message": str(exc)})
        finally:
            if path is not None:
                self._voice_service.cleanup_upload(path)
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
        path: Path | None = None
        try:
            await connection.send({"type": "voice.input.finalizing", "generation": generation})
            path = self._voice_service.save_pcm16_temp(pcm16, session.sample_rate)
            await self._on_utterance(session.session_id, path, session.language, connection)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await connection.send({"type": "voice.input.error", "message": str(exc)})
        finally:
            if path is not None:
                self._voice_service.cleanup_upload(path)
            if self._candidate_is_current(session, generation, candidate_id):
                session.pending_turn.clear()
                session.pending_candidate_id = None

    @staticmethod
    def _clear_endpoint_task(session: InputSession, task: asyncio.Task) -> None:
        if session.endpoint_task is task:
            session.endpoint_task = None
