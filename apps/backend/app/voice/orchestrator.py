from __future__ import annotations

import asyncio
import io
import logging
import time
import wave
from pathlib import Path
from uuid import uuid4

from apps.backend.app.voice.delivery import SpeechSegment, plan_speech
from apps.backend.app.voice.providers import TTSRequest, TTSResult, split_tts_chunks
from apps.backend.app.voice.style import VoiceStyle

logger = logging.getLogger(__name__)


class SpeechOrchestrator:
    """Shared, fail-soft full-WAV path for avatar and browser batch playback."""

    def __init__(self, voice_service, event_bus, settings, avatar_service) -> None:
        self.voice_service = voice_service
        self.event_bus = event_bus
        self.settings = settings
        self.avatar_service = avatar_service
        self._tasks: set[asyncio.Task[None]] = set()
        self._tasks_by_session: dict[str, set[asyncio.Task[None]]] = {}

    def enqueue(
        self,
        *,
        session_id: str,
        reply: str,
        emotion: str,
        intent: str,
        gesture: str = "auto",
        gesture_intensity: float = 1.0,
        voice: str,
        style: VoiceStyle | str = VoiceStyle.AUTO,
        interrupt: bool = True,
        voice_request_id: str | None = None,
        delivery=None,
        playback_rate: float = 1.0,
    ) -> str:
        request_id = voice_request_id or uuid4().hex
        self.voice_service.set_tts_job(
            request_id, {"status": "queued", "audio_url": None, "voice": voice}
        )
        task = asyncio.create_task(
            self._run(
                session_id=session_id,
                voice_request_id=request_id,
                reply=reply,
                emotion=emotion,
                intent=intent,
                gesture=gesture,
                gesture_intensity=gesture_intensity,
                voice=voice,
                style=style,
                interrupt=interrupt,
                delivery=delivery,
                playback_rate=playback_rate,
            )
        )
        self._tasks.add(task)
        self._tasks_by_session.setdefault(session_id, set()).add(task)

        def discard(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            session_tasks = self._tasks_by_session.get(session_id)
            if session_tasks is None:
                return
            session_tasks.discard(completed)
            if not session_tasks:
                self._tasks_by_session.pop(session_id, None)

        task.add_done_callback(discard)
        return request_id

    def bind_runtime(self, voice_service, settings) -> None:
        """Keep the singleton usable with FastAPI test/application state overrides."""
        self.voice_service = voice_service
        self.settings = settings

    async def close(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel_session(self, session_id: str) -> int:
        """Cancel queued or synthesizing full-WAV speech for one conversation."""
        tasks = list(self._tasks_by_session.get(session_id, set()))
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    async def _run(
        self,
        *,
        session_id: str,
        voice_request_id: str,
        reply: str,
        emotion: str,
        intent: str,
        gesture: str,
        gesture_intensity: float,
        voice: str,
        style: VoiceStyle | str,
        interrupt: bool,
        delivery,
        playback_rate: float,
    ) -> None:
        output_path = self.voice_service.next_tts_path(self.settings.voice_tts_provider)
        text = reply.strip()[: self.settings.voice_tts_max_chars]
        self.event_bus.publish(
            "voice.tts_started", "info", "Voice synthesis started",
            {"session_id": session_id, "voice_request_id": voice_request_id, "voice": voice,
             "text_length": len(text), "chunks_count": len(split_tts_chunks(text))},
        )
        try:
            result = await asyncio.wait_for(
                self._synthesize_plan(
                    text,
                    voice,
                    output_path,
                    style,
                    delivery,
                    playback_rate,
                ),
                timeout=self.settings.voice_tts_background_timeout_seconds,
            )
            if not result.audio_path.exists() or not result.audio_path.is_file():
                raise FileNotFoundError("TTS provider did not create a WAV file")
        except asyncio.CancelledError:
            self.voice_service.set_tts_job(
                voice_request_id,
                {"status": "cancelled", "audio_url": None, "voice": voice},
            )
            self.event_bus.publish(
                "voice.tts_cancelled",
                "info",
                "Voice synthesis cancelled by user speech",
                {"session_id": session_id, "voice_request_id": voice_request_id, "voice": voice},
            )
            raise
        except TimeoutError:
            self._fail(session_id, voice_request_id, voice, "Voice synthesis timed out", "TimeoutError")
        except Exception as exc:
            logger.info("Voice synthesis failed: voice_request_id=%s voice=%s error_type=%s", voice_request_id, voice, type(exc).__name__)
            logger.debug("Voice synthesis fallback details", exc_info=True)
            self._fail(session_id, voice_request_id, voice, "Voice synthesis failed", type(exc).__name__)
        else:
            audio_url = f"/voice/audio/{result.audio_path.name}"
            self.voice_service.set_tts_job(
                voice_request_id,
                {"status": "ready", "audio_url": audio_url, "voice": result.voice,
                 "duration_ms": result.duration_ms, "chunks_count": result.chunks_count,
                 "audio_duration_seconds": result.audio_duration_seconds},
            )
            self.event_bus.publish(
                "voice.tts_ready", "info", "Voice synthesis ready",
                {"session_id": session_id, "voice_request_id": voice_request_id, "audio_url": audio_url,
                 "duration_ms": result.duration_ms, "voice": result.voice,
                 "chunks_count": result.chunks_count, "audio_duration_seconds": result.audio_duration_seconds},
            )
            await self.avatar_service.speak(
                session_id=session_id, utterance_id=voice_request_id, text=text, audio_url=audio_url,
                emotion=emotion, intent=intent, gesture=gesture,
                gesture_intensity=gesture_intensity, interrupt=interrupt,
            )

    async def _synthesize_plan(
        self,
        text: str,
        voice: str,
        output_path: Path,
        style: VoiceStyle | str,
        delivery,
        playback_rate: float,
    ) -> TTSResult:
        started = time.perf_counter()
        provider = self.voice_service.tts_provider
        if not callable(getattr(provider, "stream", None)):
            return await provider.synthesize(text, voice, output_path, style)
        segments = plan_speech(text, delivery)
        if not segments:
            raise ValueError("No speakable text")
        rate = max(0.75, min(1.25, float(playback_rate)))
        pcm_parts: list[bytes] = []
        wave_params: tuple[int, int, int] | None = None
        for segment in segments:
            effective = SpeechSegment(
                text=segment.text,
                pace=segment.pace,
                tempo=max(0.75, min(1.25, segment.tempo * rate)),
                emphasis=segment.emphasis,
                pause_before_ms=segment.pause_before_ms,
                pause_after_ms=segment.pause_after_ms,
                sequence=segment.sequence,
            )
            request = TTSRequest(
                text=effective.text,
                language="ru",
                voice=voice,
                style=style,
                pace=effective.pace,
                tempo=effective.tempo,
                emphasis=effective.emphasis,
                pause_before_ms=effective.pause_before_ms,
                pause_after_ms=effective.pause_after_ms,
            )
            chunks = [chunk.data async for chunk in provider.stream(request) if chunk.data]
            if not chunks:
                raise RuntimeError("TTS provider returned empty audio")
            with wave.open(io.BytesIO(b"".join(chunks)), "rb") as source:
                current_params = (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                )
                if wave_params is None:
                    wave_params = current_params
                elif current_params != wave_params:
                    raise RuntimeError("TTS segments use incompatible WAV formats")
                pcm_parts.append(source.readframes(source.getnframes()))
        assert wave_params is not None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(wave_params[0])
            output.setsampwidth(wave_params[1])
            output.setframerate(wave_params[2])
            output.writeframes(b"".join(pcm_parts))
        frame_count = len(b"".join(pcm_parts)) // (wave_params[0] * wave_params[1])
        return TTSResult(
            audio_path=output_path,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider=provider.name,
            voice=voice,
            chunks_count=len(segments),
            audio_duration_seconds=frame_count / wave_params[2],
        )

    def _fail(self, session_id: str, voice_request_id: str, voice: str, error: str, error_type: str) -> None:
        self.voice_service.set_tts_job(
            voice_request_id,
            {"status": "failed", "audio_url": None, "voice": voice, "error": error,
             "error_type": error_type, "recoverable": True, "fallback": "browser_speech"},
        )
        self.event_bus.publish(
            "voice.tts_failed", "warning", error,
            {"session_id": session_id, "voice_request_id": voice_request_id, "voice": voice,
             "failed_chunk_index": None, "error_type": error_type, "recoverable": True,
             "fallback": "browser_speech"},
        )
