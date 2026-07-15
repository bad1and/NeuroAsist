import asyncio
import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.backend.app.api.routes.chat import router as chat_router
from apps.backend.app.api.routes.avatar import router as avatar_router
from apps.backend.app.api.routes.events import router as events_router
from apps.backend.app.api.routes.settings import router as settings_router
from apps.backend.app.api.routes.status import router as status_router
from apps.backend.app.api.routes.voice import router as voice_router
from apps.backend.app.api.websocket import router as websocket_router
from apps.backend.app.core.config import get_settings
from apps.backend.app.core.logging import configure_logging
from apps.backend.app.events.bus import EventBus
from apps.backend.app.avatar.connection_manager import AvatarConnectionManager
from apps.backend.app.avatar.service import AvatarService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory
from apps.backend.app.voice.service import VoiceService
from apps.backend.app.voice.live import VoiceSessionManager
from apps.backend.app.voice.orchestrator import SpeechOrchestrator

logger = logging.getLogger(__name__)

TTS_AUDIO_CLEANUP_INTERVAL_SECONDS = 20 * 60
TTS_AUDIO_RETENTION_SECONDS = 2 * 60


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    if not settings.llm_api_key:
        logger.warning("DeepSeek API key is not configured")

    app = FastAPI(title=settings.app_name, version="0.4.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    history = SQLiteMessageHistory(settings.database_path)
    event_bus = EventBus(max_events=300)
    runtime_settings = RuntimeSettings(
        voice_language=settings.voice_default_language,
        voice_tts_voice=settings.voice_silero_speaker_ru,
        voice_live_playback_prebuffer_segments=settings.voice_live_playback_prebuffer_segments,
        voice_live_playback_prebuffer_ms=settings.voice_live_playback_prebuffer_ms,
    )
    voice_service = VoiceService(settings)
    voice_session_manager = VoiceSessionManager(
        voice_service.tts_provider,
        queue_size=settings.voice_live_queue_size,
        tts_timeout=settings.voice_tts_timeout_seconds,
        retry_count=settings.voice_live_tts_retry_count,
        idle_flush_ms=settings.voice_live_idle_flush_ms,
        first_segment_chars=settings.voice_live_first_segment_chars,
        next_segment_chars=settings.voice_live_next_segment_chars,
        max_segment_chars=settings.voice_live_max_segment_chars,
        max_segment_words=settings.voice_live_max_segment_words,
        safe_segment_words=settings.voice_live_safe_segment_words,
        tts_concurrency_mode=settings.voice_live_tts_concurrency_mode,
        tts_concurrency_min=settings.voice_live_tts_concurrency_min,
        tts_concurrency_max=settings.voice_live_tts_concurrency_max,
        event_publisher=event_bus.publish,
    )
    avatar_service = AvatarService(
        AvatarConnectionManager(), event_bus,
        enabled=settings.avatar_enabled,
        heartbeat_interval_seconds=settings.avatar_heartbeat_interval_seconds,
        client_timeout_seconds=settings.avatar_client_timeout_seconds,
    )
    voice_session_manager.bind_avatar_service(avatar_service)
    speech_orchestrator = SpeechOrchestrator(voice_service, event_bus, settings, avatar_service)
    tts_audio_cleanup_task: asyncio.Task[None] | None = None

    async def cleanup_tts_audio_forever() -> None:
        try:
            while True:
                await asyncio.sleep(TTS_AUDIO_CLEANUP_INTERVAL_SECONDS)
                removed = await asyncio.to_thread(
                    voice_service.cleanup_tts_audio,
                    max_age_seconds=TTS_AUDIO_RETENTION_SECONDS,
                )
                if removed:
                    logger.info("Generated WAV cleanup complete: removed=%s", removed)
        except asyncio.CancelledError:
            raise

    @app.on_event("startup")
    async def startup() -> None:
        nonlocal tts_audio_cleanup_task
        removed = await asyncio.to_thread(voice_service.clear_tts_audio)
        if removed:
            logger.info("Generated WAV startup cleanup complete: removed=%s", removed)

        try:
            history.init_db()
        except Exception:
            logger.critical("Storage initialization failed", exc_info=True)
            event_bus.publish(
                "backend.status",
                "critical",
                "Storage initialization failed",
                {},
            )
            raise

        if settings.voice_preload_stt_model:
            try:
                await voice_service.preload_stt()
                event_bus.publish(
                    "voice.stt_preloaded",
                    "info",
                    "Voice STT model preloaded",
                    {"provider": settings.voice_stt_provider, "model": settings.voice_stt_model},
                )
            except Exception:
                logger.warning("Voice STT preload failed", exc_info=True)
                event_bus.publish(
                    "voice.stt_preload_failed",
                    "warning",
                    "Voice STT preload failed; first request will retry lazy load",
                    {"provider": settings.voice_stt_provider, "model": settings.voice_stt_model},
                )

        if settings.voice_preload_tts_model and settings.voice_tts_enabled:
            event_bus.publish(
                "voice.tts_preloading_started",
                "info",
                "Voice TTS model preloading started",
                {
                    "provider": voice_service.tts_provider.name,
                    "model": settings.voice_silero_model,
                    "speaker": settings.voice_silero_speaker_ru,
                    "device": settings.voice_silero_device,
                },
            )
            preload_started = time.perf_counter()
            try:
                await voice_service.preload_tts()
                duration_ms = int((time.perf_counter() - preload_started) * 1000)
                event_bus.publish(
                    "voice.tts_preloaded",
                    "info",
                    "Voice TTS model preloaded",
                    {
                        "provider": voice_service.tts_provider.name,
                        "model": settings.voice_silero_model,
                        "speaker": settings.voice_silero_speaker_ru,
                        "device": settings.voice_silero_device,
                        "duration_ms": duration_ms,
                    },
                )
                if settings.voice_silero_warmup:
                    event_bus.publish(
                        "voice.tts_warmed_up",
                        "info",
                        "Voice TTS model warmed up",
                        {
                            "provider": voice_service.tts_provider.name,
                            "model": settings.voice_silero_model,
                            "speaker": settings.voice_silero_speaker_ru,
                            "device": settings.voice_silero_device,
                            "duration_ms": duration_ms,
                        },
                    )
            except Exception:
                logger.warning("Voice TTS preload failed", exc_info=True)
                event_bus.publish(
                    "voice.tts_preload_failed",
                    "warning",
                    "Voice TTS preload failed; browser speech fallback remains available",
                    {
                        "provider": voice_service.tts_provider.name,
                        "model": settings.voice_silero_model,
                        "speaker": settings.voice_silero_speaker_ru,
                        "device": settings.voice_silero_device,
                    },
                )

        event_bus.publish(
            "backend.status",
            "info",
            "Backend startup complete",
            {"version": app.version},
        )
        logger.info("Backend startup complete")

        await avatar_service.start()
        tts_audio_cleanup_task = asyncio.create_task(cleanup_tts_audio_forever())

    @app.on_event("shutdown")
    async def shutdown() -> None:
        if tts_audio_cleanup_task is not None:
            tts_audio_cleanup_task.cancel()
            try:
                await tts_audio_cleanup_task
            except asyncio.CancelledError:
                pass
        await speech_orchestrator.close()
        await avatar_service.close()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.state.settings = settings
    app.state.history = history
    app.state.event_bus = event_bus
    app.state.runtime_settings = runtime_settings
    app.state.voice_service = voice_service
    app.state.voice_session_manager = voice_session_manager
    app.state.avatar_service = avatar_service
    app.state.speech_orchestrator = speech_orchestrator
    app.include_router(chat_router)
    app.include_router(avatar_router)
    app.include_router(events_router)
    app.include_router(settings_router)
    app.include_router(status_router)
    app.include_router(voice_router)
    app.include_router(websocket_router)
    return app


app = create_app()
