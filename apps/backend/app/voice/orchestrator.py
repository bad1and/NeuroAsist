from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from apps.backend.app.voice.providers import split_tts_chunks
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
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
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
                self.voice_service.tts_provider.synthesize(text, voice, output_path, style),
                timeout=self.settings.voice_tts_background_timeout_seconds,
            )
            if not result.audio_path.exists() or not result.audio_path.is_file():
                raise FileNotFoundError("TTS provider did not create a WAV file")
        except asyncio.CancelledError:
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
