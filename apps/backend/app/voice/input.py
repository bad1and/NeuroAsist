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
    finalizing: bool = False


UtteranceHandler = Callable[[str, Path, str, InputConnection], Awaitable[None]]
SpeechStartedHandler = Callable[[str], Awaitable[None]]


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
    ) -> None:
        self._voice_service = voice_service
        self._on_utterance = on_utterance
        self._on_speech_started = on_speech_started
        self._vad = vad or VadProvider()
        self._vad_threshold = max(0.05, min(.95, vad_threshold))
        self._pre_roll_ms = pre_roll_ms
        self._max_utterance_seconds = max_utterance_seconds
        self._sessions: dict[str, InputSession] = {}

    @property
    def vad_status(self) -> dict[str, object]:
        return {"provider": self._vad.name, "ready": getattr(self._vad, "ready", True), "error": getattr(self._vad, "error", None)}

    async def register(self, session_id: str, websocket: WebSocket) -> InputConnection:
        connection = InputConnection(websocket)
        self._sessions[session_id] = InputSession(session_id, connection)
        return connection

    async def unregister(self, session_id: str, connection: InputConnection) -> None:
        if self._sessions.get(session_id, None) and self._sessions[session_id].connection is connection:
            self._sessions.pop(session_id, None)

    async def start(self, session_id: str, *, sample_rate: int, channels: int, language: str) -> None:
        session = self._sessions[session_id]
        if sample_rate not in {8000, 16000, 24000, 48000} or channels != 1:
            raise ValueError("PCM input requires mono 8/16/24/48 kHz audio")
        session.sample_rate, session.channels, session.language = sample_rate, channels, language
        session.gate = VadGate(threshold=self._vad_threshold)
        session.ring.clear(); session.ring_bytes = 0; session.utterance = None; session.finalizing = False
        await session.connection.send({"type": "voice.input.ready", "sample_rate": sample_rate, "vad": self.vad_status})

    async def feed(self, session_id: str, pcm16: bytes) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.finalizing or not pcm16:
            return
        if len(pcm16) % 2:
            await session.connection.send({"type": "voice.input.error", "message": "PCM16 frame has an odd byte length"})
            return
        self._append_ring(session, pcm16)
        event = session.gate.feed(self._vad.probability(pcm16, session.sample_rate), time.monotonic())
        if event == "speech_started":
            session.utterance = bytearray().join(session.ring)
            if self._on_speech_started is not None:
                await self._on_speech_started(session_id)
            await session.connection.send({"type": "voice.input.speech_started"})
        elif session.utterance is not None:
            session.utterance.extend(pcm16)
            if len(session.utterance) > session.sample_rate * 2 * self._max_utterance_seconds:
                event = "speech_ended"
        if event == "speech_ended" and session.utterance is not None:
            audio = bytes(session.utterance)
            session.utterance = None
            session.finalizing = True
            asyncio.create_task(self._finalize(session, audio), name=f"voice-input-{session_id}")

    def _append_ring(self, session: InputSession, pcm16: bytes) -> None:
        session.ring.append(pcm16)
        session.ring_bytes += len(pcm16)
        max_bytes = int(session.sample_rate * 2 * self._pre_roll_ms / 1000)
        while session.ring and session.ring_bytes > max_bytes:
            session.ring_bytes -= len(session.ring.popleft())

    async def _finalize(self, session: InputSession, pcm16: bytes) -> None:
        path: Path | None = None
        try:
            await session.connection.send({"type": "voice.input.finalizing"})
            path = self._voice_service.save_pcm16_temp(pcm16, session.sample_rate)
            await self._on_utterance(session.session_id, path, session.language, session.connection)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await session.connection.send({"type": "voice.input.error", "message": str(exc)})
        finally:
            if path is not None:
                self._voice_service.cleanup_upload(path)
            session.finalizing = False
