import asyncio
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.backend.app.api.routes.chat import router as chat_router
from apps.backend.app.api.routes.avatar import router as avatar_router
from apps.backend.app.api.routes.events import router as events_router
from apps.backend.app.api.routes.settings import router as settings_router
from apps.backend.app.api.routes.status import router as status_router
from apps.backend.app.api.routes.voice import router as voice_router
from apps.backend.app.api.routes.timeline import router as timeline_router
from apps.backend.app.api.routes.episodes import router as episodes_router
from apps.backend.app.api.routes.context_debug import router as context_debug_router
from apps.backend.app.api.routes.memory import router as memory_router
from apps.backend.app.api.routes.models import router as models_router
from apps.backend.app.api.routes.maintenance import router as maintenance_router
from apps.backend.app.api.websocket import router as websocket_router
from apps.backend.app.core.config import get_settings
from apps.backend.app.core.logging import configure_logging
from apps.backend.app.events.bus import EventBus
from apps.backend.app.avatar.connection_manager import AvatarConnectionManager
from apps.backend.app.avatar.service import AvatarService
from apps.backend.app.avatar.emotion_engine import EmotionEngine
from apps.backend.app.avatar.schemas import OverlayPayload
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore
from apps.backend.app.model_manager.service import ModelManager
from apps.backend.app.storage.backups import BackupService
from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory
from apps.backend.app.storage.timeline import EpisodePolicy, TimelineHistoryAdapter, TimelineStore
from apps.backend.app.context.manager import ContextManager
from apps.backend.app.runtime.summary_worker import SummaryWorker
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.semantic.embedding import HashEmbeddingProvider
from apps.backend.app.semantic.vector_index import NullVectorIndex, SqliteVecIndex
from apps.backend.app.voice.service import VoiceService
from apps.backend.app.voice.live import VoiceSessionManager
from apps.backend.app.voice.input import SileroVadProvider, VadProvider, VoiceInputSessionManager
from apps.backend.app.voice.orchestrator import SpeechOrchestrator
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider

logger = logging.getLogger(__name__)

TTS_AUDIO_CLEANUP_INTERVAL_SECONDS = 20 * 60
TTS_AUDIO_RETENTION_SECONDS = 2 * 60


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    if not settings.llm_api_key:
        logger.warning("DeepSeek API key is not configured")

    app = FastAPI(title=settings.app_name, version="0.6.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_desktop_token(request: Request, call_next):
        """Secure the ephemeral desktop core without changing the browser/dev contract."""
        expected_token = settings.desktop_auth_token
        if (
            expected_token
            and request.method != "OPTIONS"
            and request.headers.get("x-neuroasist-token") != expected_token
        ):
            return JSONResponse(status_code=401, content={"detail": "Desktop core authentication required"})
        return await call_next(request)

    event_bus = EventBus(max_events=300)
    timeline_store = TimelineStore(
        settings.database_path,
        EpisodePolicy(
            enabled=settings.episodes_enabled,
            soft_inactivity_seconds=settings.episode_soft_inactivity_minutes * 60,
            hard_inactivity_seconds=settings.episode_hard_inactivity_minutes * 60,
            maximum_messages=settings.episode_maximum_messages,
            maximum_tokens=settings.episode_maximum_estimated_tokens,
        ),
        event_bus.publish,
    ) if settings.timeline_v2_enabled else None
    history = TimelineHistoryAdapter(timeline_store) if timeline_store is not None else SQLiteMessageHistory(settings.database_path)
    runtime_defaults = RuntimeSettings(
        voice_language=settings.voice_default_language,
        voice_tts_voice=settings.voice_silero_speaker_ru,
        voice_live_playback_prebuffer_segments=settings.voice_live_playback_prebuffer_segments,
        voice_live_playback_prebuffer_ms=settings.voice_live_playback_prebuffer_ms,
        memory_mode=settings.memory_mode,
    )
    runtime_settings_store = RuntimeSettingsStore(settings.app_data_path / "settings.json")
    runtime_settings = runtime_settings_store.load(runtime_defaults)
    model_manager = ModelManager(settings.app_data_path / "models", event_bus.publish)
    backup_service = BackupService(
        settings.app_data_path / "backups",
        settings.database_path,
        runtime_settings_store.path,
        settings.backup_retention_days,
    )
    semantic_mode_enabled = settings.semantic_retrieval_enabled and settings.semantic_retrieval_eval_passed
    if timeline_store is not None and semantic_mode_enabled and settings.semantic_embedding_provider == "hash":
        embedding_provider = HashEmbeddingProvider(settings.semantic_embedding_model_id, settings.semantic_embedding_dimension)
        vector_index = SqliteVecIndex(settings.database_path, embedding_provider, timeline_store.semantic_index_items)
    else:
        vector_index = NullVectorIndex()
    memory_service = MemoryService(
        timeline_store, runtime_settings,
        enabled=settings.memory_enabled,
        sensitive_mode=settings.memory_sensitive_mode,
        max_candidates_per_turn=settings.memory_max_candidates_per_turn,
        context_max_tokens=settings.memory_context_max_tokens,
        vector_index=vector_index,
        semantic_enabled=semantic_mode_enabled,
        semantic_limit=settings.semantic_retrieval_limit,
    ) if timeline_store is not None else None
    context_manager = ContextManager(timeline_store, settings.context_max_tokens, settings.context_recent_turns, memory_service) if timeline_store is not None and settings.context_manager_enabled else None
    summary_worker = SummaryWorker(timeline_store, memory_service.index_episode_summary if memory_service is not None else None) if timeline_store is not None else None
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
    def persist_avatar_overlay_bounds(overlay: OverlayPayload) -> None:
        runtime_settings.avatar_overlay_x = overlay.x
        runtime_settings.avatar_overlay_y = overlay.y
        runtime_settings.avatar_overlay_width = overlay.width
        runtime_settings.avatar_overlay_height = overlay.height
        runtime_settings_store.save(runtime_settings)

    avatar_service = AvatarService(
        AvatarConnectionManager(), event_bus,
        enabled=settings.avatar_enabled,
        heartbeat_interval_seconds=settings.avatar_heartbeat_interval_seconds,
        client_timeout_seconds=settings.avatar_client_timeout_seconds,
        emotion_engine=EmotionEngine.from_path(settings.avatar_emotion_mapping),
        overlay=OverlayPayload(
            visible=runtime_settings.avatar_overlay_visible,
            always_on_top=runtime_settings.avatar_overlay_always_on_top,
            locked=runtime_settings.avatar_overlay_locked,
            scale=runtime_settings.avatar_overlay_scale,
            monitor=runtime_settings.avatar_overlay_monitor,
            x=runtime_settings.avatar_overlay_x,
            y=runtime_settings.avatar_overlay_y,
            width=runtime_settings.avatar_overlay_width,
            height=runtime_settings.avatar_overlay_height,
        ),
        on_overlay_bounds_changed=persist_avatar_overlay_bounds,
    )
    voice_session_manager.bind_avatar_service(avatar_service)
    vad_model_path = settings.voice_silero_vad_model or model_manager.path_for("silero-vad")
    vad_provider = SileroVadProvider(vad_model_path) if settings.voice_vad_provider == "silero" else VadProvider()

    async def process_pcm_utterance(session_id, audio_path, language, connection) -> None:
        stt_result = await voice_service.stt_provider.transcribe(audio_path, language)
        if not stt_result.text.strip():
            await connection.send({"type": "voice.input.error", "message": "Could not transcribe speech"})
            return
        if not voice_session_manager.connected(session_id):
            await connection.send({"type": "voice.input.error", "message": "Live output WebSocket is not connected"})
            return
        agent = CharacterAgent(
            llm_provider=DeepSeekProvider(settings), history=history, history_limit=settings.chat_history_limit,
            event_publisher=event_bus.publish, context_manager=context_manager, memory_service=memory_service,
            persona_name=runtime_settings.personality,
        )
        utterance_id = __import__("uuid").uuid4().hex
        voice = voice_service.resolve_tts_voice(language, runtime_settings.voice_tts_voice)
        await connection.send({"type": "voice.input.transcript", "transcript": stt_result.text, "utterance_id": utterance_id})
        await voice_session_manager.start(
            session_id=session_id, utterance_id=utterance_id, transcript=stt_result.text,
            language=stt_result.language, voice=voice, agent=agent,
        )

    async def pcm_speech_started(session_id: str) -> None:
        await voice_session_manager.cancel(session_id)

    voice_input_session_manager = VoiceInputSessionManager(
        voice_service, process_pcm_utterance, pcm_speech_started,
        vad=vad_provider, vad_threshold=settings.voice_vad_threshold, pre_roll_ms=settings.voice_vad_pre_roll_ms,
    )
    speech_orchestrator = SpeechOrchestrator(voice_service, event_bus, settings, avatar_service)
    tts_audio_cleanup_task: asyncio.Task[None] | None = None
    summary_worker_task: asyncio.Task[None] | None = None

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

    async def summarize_forever() -> None:
        if summary_worker is None:
            return
        try:
            while True:
                worked = await summary_worker.run_once()
                await asyncio.sleep(0 if worked else 1)
        except asyncio.CancelledError:
            raise

    @app.on_event("startup")
    async def startup() -> None:
        nonlocal tts_audio_cleanup_task, summary_worker_task
        removed = await asyncio.to_thread(voice_service.clear_tts_audio)
        if removed:
            logger.info("Generated WAV startup cleanup complete: removed=%s", removed)

        try:
            history.init_db()
            if timeline_store is not None:
                timeline_store.recover_active_episode()
            if memory_service is not None:
                repaired = memory_service.repair_legacy_identity_candidates()
                if repaired:
                    event_bus.publish(
                        "memory.legacy_identity_repaired",
                        "info",
                        "Legacy identity memories repaired",
                        {"count": len(repaired)},
                    )
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
        summary_worker_task = asyncio.create_task(summarize_forever())

    @app.on_event("shutdown")
    async def shutdown() -> None:
        if timeline_store is not None:
            await asyncio.to_thread(timeline_store.close_current_episode, "application_shutdown")
        if summary_worker is not None:
            try:
                await asyncio.wait_for(summary_worker.run_once(), timeout=1)
            except (TimeoutError, Exception):
                logger.warning("Bounded shutdown summary pass did not complete", exc_info=True)
        if tts_audio_cleanup_task is not None:
            tts_audio_cleanup_task.cancel()
            try:
                await tts_audio_cleanup_task
            except asyncio.CancelledError:
                pass
        if summary_worker_task is not None:
            summary_worker_task.cancel()
            try:
                await summary_worker_task
            except asyncio.CancelledError:
                pass
        await speech_orchestrator.close()
        await avatar_service.close()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.state.settings = settings
    app.state.history = history
    app.state.timeline_store = timeline_store
    app.state.context_manager = context_manager
    app.state.memory_service = memory_service
    app.state.event_bus = event_bus
    app.state.runtime_settings = runtime_settings
    app.state.runtime_settings_store = runtime_settings_store
    app.state.model_manager = model_manager
    app.state.backup_service = backup_service
    app.state.voice_service = voice_service
    app.state.voice_session_manager = voice_session_manager
    app.state.voice_input_session_manager = voice_input_session_manager
    app.state.avatar_service = avatar_service
    app.state.speech_orchestrator = speech_orchestrator
    app.include_router(chat_router)
    app.include_router(avatar_router)
    app.include_router(events_router)
    app.include_router(settings_router)
    app.include_router(status_router)
    app.include_router(voice_router)
    app.include_router(timeline_router)
    app.include_router(episodes_router)
    app.include_router(context_debug_router)
    app.include_router(memory_router)
    app.include_router(models_router)
    app.include_router(maintenance_router)
    app.include_router(websocket_router)
    return app


app = create_app()
