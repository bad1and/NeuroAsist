import asyncio
import logging
import re
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import contextlib
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.backend.app.api.routes.chat import router as chat_router
from apps.backend.app.api.routes.avatar import router as avatar_router
from apps.backend.app.api.routes.events import router as events_router
from apps.backend.app.api.routes.settings import _commit_runtime_settings_patch, router as settings_router
from apps.backend.app.api.routes.status import router as status_router
from apps.backend.app.api.routes.voice import router as voice_router
from apps.backend.app.api.routes.timeline import router as timeline_router
from apps.backend.app.api.routes.episodes import router as episodes_router
from apps.backend.app.api.routes.context_debug import router as context_debug_router
from apps.backend.app.api.routes.llm_diagnostics import router as llm_diagnostics_router
from apps.backend.app.api.routes.memory import router as memory_router
from apps.backend.app.api.routes.models import router as models_router
from apps.backend.app.api.routes.maintenance import router as maintenance_router
from apps.backend.app.api.routes.conversation import router as conversation_router
from apps.backend.app.api.routes.coding import router as coding_router
from apps.backend.app.api.websocket import router as websocket_router
from apps.backend.app.core.config import ROOT_DIR, get_settings
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
from apps.backend.app.storage.timeline import (
    LATEST_SCHEMA_VERSION,
    EpisodePolicy,
    TimelineHistoryAdapter,
    TimelineStore,
)
from apps.backend.app.context.manager import ContextManager
from apps.backend.app.runtime.summary_worker import SummaryWorker
from apps.backend.app.memory.service import MemoryService
from apps.backend.app.memory.extraction_worker import MemoryExtractionWorker
from apps.backend.app.semantic.embedding import HashEmbeddingProvider, LocalE5EmbeddingProvider
from apps.backend.app.semantic.chroma_index import ChromaVectorIndex
from apps.backend.app.semantic.sync_worker import SemanticSyncWorker
from apps.backend.app.semantic.vector_index import NullVectorIndex, SqliteVecIndex
from apps.backend.app.voice.service import VoiceService
from apps.backend.app.voice.audio import Pcm16Audio
from apps.backend.app.voice.live import VoiceSessionManager
from apps.backend.app.voice.input import SileroVadProvider, VadProvider, VoiceInputSessionManager
from apps.backend.app.voice.runtime import configure_torch_threads
from apps.backend.app.voice.orchestrator import SpeechOrchestrator
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.conversation.schemas import ConversationAction, ConversationPhase, SpeakerRole
from apps.backend.app.conversation.service import LiveConversationService
from apps.backend.app.conversation.state_service import CharacterStateService
from apps.backend.app.conversation.turn_coordinator import ConversationTurnCoordinator
from apps.backend.app.conversation.turn import SmartTurnDetector
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider, close_shared_clients
from apps.backend.app.llm.telemetry import llm_telemetry
from apps.backend.app.coding.service import CodingAgentService
from apps.backend.app.coding.orchestration import CodingBridge

logger = logging.getLogger(__name__)

TTS_AUDIO_CLEANUP_INTERVAL_SECONDS = 20 * 60
TTS_AUDIO_RETENTION_SECONDS = 2 * 60
# Idle background workers back off instead of polling SQLite once a second.
# The ceiling stays low so a queued job is still picked up promptly.
IDLE_WORKER_POLL_MIN_SECONDS = 1.0
IDLE_WORKER_POLL_MAX_SECONDS = 5.0
WORKER_RESTART_MIN_SECONDS = 1.0
WORKER_RESTART_MAX_SECONDS = 30.0


async def _supervise_worker(
    name: str,
    run_forever: Callable[[], Awaitable[None]],
    publish: Callable[[str, str, str, dict[str, Any]], Any],
    *,
    restart_min_seconds: float = WORKER_RESTART_MIN_SECONDS,
    restart_max_seconds: float = WORKER_RESTART_MAX_SECONDS,
) -> None:
    """Restart an unexpected worker exit while preserving task cancellation."""
    restart_count = 0
    while True:
        failure: Exception | None = None
        try:
            await run_forever()
        except asyncio.CancelledError:
            # Shutdown owns cancellation. Treating it as a crash would revive
            # the worker while the rest of the application is being closed.
            raise
        except Exception as exc:
            failure = exc
            logger.exception("Background worker %s crashed; scheduling restart", name)
        else:
            logger.warning("Background worker %s stopped unexpectedly; scheduling restart", name)

        restart_count += 1
        restart_delay = min(
            restart_min_seconds * (2 ** min(restart_count - 1, 10)),
            restart_max_seconds,
        )
        metadata: dict[str, Any] = {
            "worker": name,
            "restart_count": restart_count,
            "restart_in_seconds": restart_delay,
        }
        if failure is not None:
            metadata.update({
                "error_type": type(failure).__name__,
                "error_message": str(failure)[:300],
            })
        try:
            publish(
                "backend.worker_failed",
                "error" if failure is not None else "warning",
                f"Background worker {name} stopped; restart scheduled",
                metadata,
            )
        except Exception:
            # Diagnostics must not become another way to lose the supervisor.
            logger.warning("Failed to publish %s worker failure", name, exc_info=True)
        await asyncio.sleep(restart_delay)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    # Torch and local voice models are intentionally not touched while the
    # ASGI application graph is being built.  The first paint only needs the
    # text stack; voice preparation starts after migrations make that stack
    # usable.
    torch_threading: dict[str, int] | None = None

    if not settings.llm_api_key:
        logger.warning("DeepSeek API key is not configured")

    app = FastAPI(title=settings.app_name, version="0.9.0")
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
        voice_tts_voice=settings.voice_tts_default_voice,
        voice_live_playback_prebuffer_segments=settings.voice_live_playback_prebuffer_segments,
        voice_live_playback_prebuffer_ms=settings.voice_live_playback_prebuffer_ms,
        memory_mode=settings.memory_mode,
    )
    runtime_settings_store = RuntimeSettingsStore(settings.app_data_path / "settings.json")
    runtime_settings = runtime_settings_store.load(runtime_defaults)
    coding_agent_service = CodingAgentService(settings, runtime_settings, timeline_store, event_bus.publish)
    coding_bridge = CodingBridge(coding_agent_service)
    app.state.voice_tts_style = "auto"
    app.state.voice_tts_expression_level = "natural"
    model_manager = ModelManager(settings.app_data_path / "models", event_bus.publish)
    backup_service = BackupService(
        settings.app_data_path / "backups",
        settings.database_path,
        runtime_settings_store.path,
        settings.backup_retention_days,
    )
    semantic_mode_enabled = settings.semantic_retrieval_enabled and settings.semantic_retrieval_eval_passed
    if settings.semantic_vector_backend == "chroma":
        installed_data_dir = (settings.app_data_path / "data").resolve()
        if settings.database_path.parent.resolve() == installed_data_dir:
            legacy_removed = ChromaVectorIndex.remove_legacy_storage_if_safe(
                ROOT_DIR / "data" / "chroma",
                settings.semantic_chroma_directory,
            )
            if legacy_removed:
                event_bus.publish(
                    "memory.legacy_index_removed",
                    "info",
                    "Obsolete shared Chroma index removed after namespace validation",
                    {"path": str(ROOT_DIR / "data" / "chroma")},
                )
        ChromaVectorIndex.clear_pending_reset(settings.semantic_chroma_directory)
    semantic_init_error: str | None = None
    if timeline_store is not None and semantic_mode_enabled and settings.semantic_embedding_provider in {"hash", "e5"}:
        try:
            embedding_provider = (
                LocalE5EmbeddingProvider(settings.semantic_e5_model_directory, settings.semantic_e5_revision)
                if settings.semantic_embedding_provider == "e5"
                else HashEmbeddingProvider(settings.semantic_embedding_model_id, settings.semantic_embedding_dimension)
            )
        except Exception:
            # Semantic retrieval is an optional cache. FTS remains available
            # when a local model is absent or cannot be loaded.
            semantic_mode_enabled = False
            embedding_provider = None
        try:
            if embedding_provider is not None and settings.semantic_vector_backend == "chroma":
                vector_index = ChromaVectorIndex(settings.semantic_chroma_directory, embedding_provider, timeline_store.semantic_index_items)
            elif embedding_provider is not None:
                vector_index = SqliteVecIndex(settings.database_path, embedding_provider, timeline_store.semantic_index_items)
            else:
                vector_index = NullVectorIndex()
        except Exception as exc:
            semantic_init_error = f"{type(exc).__name__}: {exc}"[:300]
            semantic_mode_enabled = False
            vector_index = NullVectorIndex()
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
        llm_extraction_enabled=settings.memory_llm_extraction_enabled,
        llm_min_confidence=settings.memory_llm_min_confidence,
        async_extraction_enabled=settings.memory_async_extraction_enabled,
        auto_min_confidence=settings.memory_auto_min_confidence,
        auto_min_importance=settings.memory_auto_min_importance,
    ) if timeline_store is not None else None
    context_manager = ContextManager(timeline_store, settings.context_max_tokens, settings.context_recent_turns, memory_service) if timeline_store is not None and settings.context_manager_enabled else None
    summary_worker = SummaryWorker(timeline_store, memory_service.index_episode_summary if memory_service is not None else None) if timeline_store is not None else None
    semantic_sync_worker = SemanticSyncWorker(memory_service) if memory_service is not None else None
    memory_extraction_worker = MemoryExtractionWorker(
        timeline_store,
        memory_service,
        DeepSeekProvider(settings, purpose="memory"),
        event_bus.publish,
        reflection_policy=lambda: (
            runtime_settings.reflections_enabled and not runtime_settings.memory_incognito,
            runtime_settings.reflection_min_significance,
        ),
        respect_coalescing=True,
    ) if (
        timeline_store is not None
        and memory_service is not None
        and settings.memory_llm_extraction_enabled
        and settings.memory_async_extraction_enabled
    ) else None
    character_state_service = CharacterStateService(
        timeline_store, recovery=runtime_settings.live_conversation_mood_recovery,
        reflection_policy=lambda: (runtime_settings.reflections_enabled and not runtime_settings.memory_incognito, runtime_settings.reflection_min_significance),
        event_publisher=event_bus.publish,
        reflection_llm_provider=(
            DeepSeekProvider(settings, purpose="reflection")
            if settings.llm_api_key
            else None
        ),
    ) if timeline_store is not None else None
    if memory_service is not None and semantic_init_error:
        memory_service._semantic_degraded_reason = semantic_init_error
    conversation_service = LiveConversationService(
        timeline_store,
        runtime_settings,
        memory_service=memory_service,
        event_publisher=event_bus.publish,
        llm_provider=(
            DeepSeekProvider(settings, purpose="adjudication")
            if settings.llm_api_key
            else None
        ),
        state_service=character_state_service,
    ) if timeline_store is not None else None
    turn_coordinator = ConversationTurnCoordinator(timeline_store, event_bus.publish) if timeline_store is not None else None
    voice_service = VoiceService(settings)
    available_tts_voices = voice_service.available_tts_voices()
    if runtime_settings.voice_tts_voice not in available_tts_voices:
        runtime_settings.voice_tts_voice = (
            settings.voice_tts_default_voice
            if settings.voice_tts_default_voice in available_tts_voices
            else available_tts_voices[0]
        )
        runtime_settings_store.save(runtime_settings)
    voice_session_manager = VoiceSessionManager(
        voice_service.tts_provider,
        queue_size=settings.voice_live_queue_size,
        tts_timeout=settings.voice_tts_timeout_seconds,
        retry_count=settings.voice_live_tts_retry_count,
        idle_flush_ms=settings.voice_live_idle_flush_ms,
        first_idle_flush_ms=settings.voice_live_first_idle_flush_ms,
        next_idle_flush_ms=settings.voice_live_next_idle_flush_ms,
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
    async def persist_avatar_overlay_bounds(overlay: OverlayPayload) -> None:
        await asyncio.to_thread(
            _commit_runtime_settings_patch,
            runtime_settings_store,
            runtime_settings,
            {
                "avatar_overlay_x": overlay.x,
                "avatar_overlay_y": overlay.y,
                "avatar_overlay_width": overlay.width,
                "avatar_overlay_height": overlay.height,
            },
        )

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
        audio_muted=bool(runtime_settings.voice_output_device_id),
        on_overlay_bounds_changed=persist_avatar_overlay_bounds,
    )
    voice_session_manager.bind_avatar_service(avatar_service)
    speech_orchestrator = SpeechOrchestrator(voice_service, event_bus, settings, avatar_service)

    def speak_coding_notification(session_id: str, text: str) -> None:
        """Give durable Coding Agent notices the same TTS delivery as chat replies."""
        if not settings.voice_tts_enabled or not text.strip():
            return
        voice = voice_service.resolve_tts_voice(
            runtime_settings.voice_language,
            runtime_settings.voice_tts_voice,
        )
        speech_orchestrator.enqueue(
            session_id=session_id,
            reply=text,
            emotion="neutral",
            intent="coding_task_notification",
            gesture="auto",
            voice=voice,
            style=app.state.voice_tts_style,
        )

    coding_agent_service.bind_notification_speaker(speak_coding_notification)

    if conversation_service is not None:
        voice_session_manager.bind_text_completed_handler(
            conversation_service.assistant_text_generated
        )
        avatar_service.bind_playback_finished_handler(
            conversation_service.avatar_playback_finished
        )

        async def conversation_avatar_reaction(
            session_id: str,
            emotion: str,
            intensity: float,
            generation: int,
        ) -> None:
            session = await conversation_service.ensure_session(session_id)
            if session.generation != generation:
                return
            await avatar_service.set_emotion(
                session_id=session_id,
                emotion=emotion,
                intensity=intensity,
            )
            if session.generation != generation:
                await avatar_service.stop(session_id=session_id)

        async def conversation_deferred_response(
            session_id: str,
            reaction,
            generation: int,
            utterance_id: str,
        ) -> None:
            session = await conversation_service.ensure_session(session_id)
            if (
                session.generation != generation
                or not voice_session_manager.connected(session_id)
            ):
                return
            agent = CharacterAgent(
                llm_provider=DeepSeekProvider(settings),
                history=history,
                history_limit=settings.chat_history_limit,
                event_publisher=event_bus.publish,
                context_manager=context_manager,
                memory_service=memory_service,
                persona_name=runtime_settings.personality,
                coding_bridge=coding_bridge,
            )
            source_message = (
                await asyncio.to_thread(
                    timeline_store.get_message,
                    reaction.source_message_id,
                )
                if reaction.source_message_id
                else None
            )
            voice = voice_service.resolve_tts_voice(
                reaction.language,
                runtime_settings.voice_tts_voice,
            )
            await voice_session_manager.start(
                session_id=session_id,
                utterance_id=utterance_id,
                transcript=reaction.transcript,
                language=reaction.language,
                voice=voice,
                agent=agent,
                generation=generation,
                source_message=source_message,
                state_context=reaction.state_context,
            )

        conversation_service.bind_action_handlers(
            avatar_reaction=conversation_avatar_reaction,
            deferred_response=conversation_deferred_response,
        )

    async def interrupt_voice_session(session_id: str, utterance_id: str | None = None) -> dict[str, int]:
        """Unified barge-in cancellation for streaming, batch TTS and avatar audio."""
        await voice_session_manager.cancel(session_id, utterance_id)
        batch_cancelled = await speech_orchestrator.cancel_session(session_id)
        await avatar_service.stop(session_id=session_id, utterance_id=utterance_id)
        event_bus.publish(
            "voice.interrupted",
            "info",
            "Assistant speech interrupted by user input",
            {"session_id": session_id, "utterance_id": utterance_id, "batch_cancelled": batch_cancelled},
        )
        return {"batch": batch_cancelled}

    # Start with a zero-dependency fallback. Optional VAD and turn-detection
    # runtimes are replaced atomically by background startup tasks once their
    # models are available.
    vad_model_path = settings.voice_silero_vad_model or model_manager.path_for("silero-vad")
    vad_provider = VadProvider()
    turn_detector = SmartTurnDetector(None)
    if conversation_service is not None:
        conversation_service.bind_turn_detector(turn_detector)

    async def process_pcm_utterance(
        session_id,
        audio: Pcm16Audio,
        language,
        connection,
    ) -> None:
        # The VAD has already confirmed human speech. Only now do we leave the
        # attentive listening pose: processing an unconfirmed audio frame would
        # make the avatar twitch on room noise.
        await avatar_service.set_presence(session_id=session_id, state="thinking")
        if conversation_service is not None:
            await conversation_service.phase(session_id, ConversationPhase.TRANSCRIBING, connection.send)
        stt_result = await voice_service.transcribe_pcm16(audio, language)
        transcript = stt_result.text.strip()
        if not transcript:
            if conversation_service is not None:
                await connection.send({
                    "type": "conversation.noise_ignored",
                    "reason": "empty_transcript",
                    "generation": connection.generation,
                })
                await conversation_service.phase(
                    session_id,
                    ConversationPhase.LISTENING,
                    connection.send,
                )
            else:
                await connection.send({"type": "voice.input.error", "message": "Could not transcribe speech"})
            await avatar_service.set_presence(session_id=session_id, state="listening")
            return
        if not voice_session_manager.connected(session_id):
            await connection.send({"type": "voice.input.error", "message": "Live output WebSocket is not connected"})
            return
        agent = CharacterAgent(
            llm_provider=DeepSeekProvider(settings), history=history, history_limit=settings.chat_history_limit,
            event_publisher=event_bus.publish, context_manager=context_manager, memory_service=memory_service,
            persona_name=runtime_settings.personality,
            coding_bridge=coding_bridge,
        )
        utterance_id = uuid.uuid4().hex
        voice = voice_service.resolve_tts_voice(language, runtime_settings.voice_tts_voice)
        stt_uncertain = stt_result.fallback or (
            stt_result.confidence is not None and stt_result.confidence < 0.6
        )
        if conversation_service is not None:
            result = await conversation_service.ingest_observation(
                session_id=session_id,
                transcript=stt_result.raw_text or stt_result.text,
                corrected_content=(
                    stt_result.text
                    if (stt_result.raw_text or stt_result.text) != stt_result.text
                    else None
                ),
                transcript_corrections=stt_result.corrections,
                language=stt_result.language,
                send=connection.send,
                expected_generation=connection.generation,
                speaker_role=(
                    SpeakerRole.UNKNOWN
                    if runtime_settings.live_conversation_participant_mode == "group"
                    else SpeakerRole.PRIMARY
                ),
                speaker_confidence=(
                    0.55
                    if runtime_settings.live_conversation_participant_mode == "group"
                    else 0.9
                ),
                stt_uncertain=stt_uncertain,
            )
            session = await conversation_service.ensure_session(session_id)
            if result.generation != session.generation:
                return
            await connection.send({
                "type": "voice.input.transcript",
                "transcript": stt_result.text,
                "raw_transcript": stt_result.raw_text,
                "corrections": list(stt_result.corrections),
                "provider": stt_result.provider,
                "model": stt_result.model,
                "confidence": stt_result.confidence,
                "fallback": stt_result.fallback,
                "fallback_reason": stt_result.fallback_reason,
                "stt_uncertain": stt_uncertain,
                "utterance_id": result.utterance_id,
                "generation": result.generation,
                "observation_only": result.decision.action not in {
                    ConversationAction.BACKCHANNEL,
                    ConversationAction.RESPOND,
                },
            })
            if result.decision.action not in {
                ConversationAction.BACKCHANNEL,
                ConversationAction.RESPOND,
            }:
                await avatar_service.set_presence(session_id=session_id, state="listening")
                return
            utterance_id = result.utterance_id
            await voice_session_manager.start(
                session_id=session_id,
                utterance_id=utterance_id,
                transcript=stt_result.text,
                language=stt_result.language,
                voice=voice,
                agent=agent,
                generation=result.generation,
                source_message=result.message,
                state_context=result.state_context,
                pipeline_started_at=connection.pipeline_started_at or None,
                raw_transcript=stt_result.raw_text,
                transcript_corrections=stt_result.corrections,
            )
            return
        await connection.send({
            "type": "voice.input.transcript",
            "transcript": stt_result.text,
            "raw_transcript": stt_result.raw_text,
            "corrections": list(stt_result.corrections),
            "provider": stt_result.provider,
            "model": stt_result.model,
            "confidence": stt_result.confidence,
            "fallback": stt_result.fallback,
            "fallback_reason": stt_result.fallback_reason,
            "utterance_id": utterance_id,
        })
        await voice_session_manager.start(
            session_id=session_id, utterance_id=utterance_id, transcript=stt_result.text,
            language=stt_result.language, voice=voice, agent=agent,
            pipeline_started_at=connection.pipeline_started_at or None,
            raw_transcript=stt_result.raw_text,
            transcript_corrections=stt_result.corrections,
        )

    async def pcm_speech_started(session_id: str) -> int | None:
        generation = (
            await conversation_service.speech_started(session_id)
            if conversation_service is not None
            else None
        )
        await interrupt_voice_session(session_id)
        await avatar_service.set_presence(session_id=session_id, state="listening")
        return generation

    def barge_in_guard_active(session_id: str) -> bool:
        session = (
            conversation_service.existing_session(session_id)
            if conversation_service is not None
            else None
        )
        return bool(
            session is not None
            and session.phase
            in {ConversationPhase.GENERATING, ConversationPhase.SPEAKING}
        )

    # A VAD boundary is only a candidate boundary. Keep the minimum silence
    # long enough for ordinary Russian phrase pauses; Smart Turn still decides
    # whether the resulting candidate is a complete turn. Older .env files
    # used very short values, so the runtime safeguards existing installs too.
    pause_profile = {
        "short": (650, 900, 1500),
        "natural": (750, 1100, 2500),
        "patient": (900, 1500, 4000),
    }.get(runtime_settings.live_conversation_pause_tolerance, (750, 1100, 2500))
    live_end_silence_ms, live_fallback_end_silence_ms, max_turn_silence_ms = pause_profile
    # Smart Turn is already the semantic guard for a candidate endpoint. Give
    # it a candidate sooner, but keep the conservative fallback unchanged when
    # the model is unavailable. An incomplete candidate remains in pending_turn
    # and continues accumulating audio; inference timeout/error still waits for
    # the existing max-turn-silence safeguard rather than speaking early.
    semantic_end_silence_ms = max(
        450,
        min(settings.voice_vad_live_end_silence_ms, live_end_silence_ms) - 250,
    )

    voice_input_session_manager = VoiceInputSessionManager(
        voice_service, process_pcm_utterance, pcm_speech_started,
        vad=vad_provider,
        silero_start_threshold=settings.voice_silero_vad_start_threshold,
        silero_end_threshold=settings.voice_silero_vad_end_threshold,
        energy_start_rms=settings.voice_energy_vad_start_rms,
        energy_end_rms=settings.voice_energy_vad_end_rms,
        silero_start_ms=settings.voice_silero_vad_min_speech_ms,
        energy_start_ms=settings.voice_energy_vad_min_speech_ms,
        # Preserve the beginning of a phrase even if browser delivery or VAD
        # confirmation arrives late. Keep existing installations safe when an
        # older .env still specifies the former 500 ms default.
        pre_roll_ms=max(settings.voice_vad_pre_roll_ms, 900),
        post_roll_ms=settings.voice_vad_post_roll_ms,
        live_end_silence_ms=max(settings.voice_vad_live_end_silence_ms, live_end_silence_ms),
        semantic_end_silence_ms=semantic_end_silence_ms,
        live_fallback_end_silence_ms=max(
            settings.voice_vad_live_fallback_end_silence_ms,
            live_fallback_end_silence_ms,
        ),
        max_turn_silence_ms=max_turn_silence_ms,
        barge_in_guard=barge_in_guard_active,
        barge_in_confirmation_ms={
            # A short, loud cough can pass VAD. Require sustained audio
            # before interrupting a response, even at high sensitivity.
            "low": 650,
            "balanced": 450,
            "high": 300,
        }.get(runtime_settings.live_conversation_interruption_sensitivity, 450),
        turn_detector=turn_detector,
        event_publisher=event_bus.publish,
    )
    initial_vad_status = voice_input_session_manager.vad_status
    initial_vad_is_fallback = settings.voice_vad_provider == "silero"
    event_bus.publish(
        "voice.vad_fallback" if initial_vad_is_fallback else "voice.vad_ready",
        "warning" if initial_vad_is_fallback else "info",
        "Energy VAD fallback is active" if initial_vad_is_fallback else "Energy VAD is ready",
        initial_vad_status,
    )
    tts_audio_cleanup_task: asyncio.Task[None] | None = None
    storage_maintenance_task: asyncio.Task[None] | None = None
    voice_preload_task: asyncio.Task[None] | None = None
    avatar_start_task: asyncio.Task[None] | None = None
    reflection_worker_task: asyncio.Task[None] | None = None
    summary_worker_task: asyncio.Task[None] | None = None
    semantic_sync_worker_task: asyncio.Task[None] | None = None
    memory_extraction_worker_task: asyncio.Task[None] | None = None
    coding_worker_task: asyncio.Task[None] | None = None

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

    async def poll_worker_forever(run_once: Callable[[], Awaitable[Any]]) -> None:
        """Drain a background queue, backing off while it stays empty.

        A flat one-second poll kept four workers hitting SQLite every second
        for the whole session, competing for WAL locks with the voice path.
        Backoff only grows while idle and collapses back to the original
        cadence as soon as there is work, so burst latency is unchanged.
        """
        idle_delay = IDLE_WORKER_POLL_MIN_SECONDS
        try:
            while True:
                worked = await run_once()
                if worked:
                    idle_delay = IDLE_WORKER_POLL_MIN_SECONDS
                    await asyncio.sleep(0)
                    continue
                await asyncio.sleep(idle_delay)
                idle_delay = min(idle_delay * 2, IDLE_WORKER_POLL_MAX_SECONDS)
        except asyncio.CancelledError:
            raise

    async def summarize_forever() -> None:
        if summary_worker is None:
            return
        await poll_worker_forever(summary_worker.run_once)

    async def sync_semantic_forever() -> None:
        if semantic_sync_worker is None:
            return
        await poll_worker_forever(semantic_sync_worker.run_once)

    async def extract_memory_forever() -> None:
        if memory_extraction_worker is None:
            return
        await poll_worker_forever(memory_extraction_worker.run_once)

    async def reflect_forever() -> None:
        if character_state_service is None:
            return
        await poll_worker_forever(character_state_service.run_reflection_once)

    async def run_coding_forever() -> None:
        await poll_worker_forever(coding_agent_service.run_once)

    def run_storage_migrations() -> None:
        """Apply schema migrations required before text chat is exposed."""
        history.init_db()

    def run_storage_repair() -> list[tuple[str, str, str, dict[str, Any]]]:
        """Synchronous startup repair chain, meant to run in a worker thread.

        Returns the events to publish instead of publishing them itself, so
        every event reaches subscribers from the event loop thread.
        """
        events: list[tuple[str, str, str, dict[str, Any]]] = []
        if timeline_store is not None:
            timeline_store.recover_active_episode()
            timeline_store.recover_memory_index_jobs()
            timeline_store.recover_coding_task_jobs()
        if memory_service is None:
            return events

        repaired = memory_service.repair_legacy_identity_candidates()
        if repaired:
            events.append((
                "memory.legacy_identity_repaired",
                "info",
                "Legacy identity memories repaired",
                {"count": len(repaired)},
            ))
        rejected_identities = memory_service.reject_invalid_interrogative_identity_memories()
        if rejected_identities:
            events.append((
                "memory.invalid_identity_rejected",
                "warning",
                "Question-derived identity memories rejected",
                {"count": len(rejected_identities)},
            ))
        rejected_assistant_facts = memory_service.reject_assistant_only_profile_memories()
        if rejected_assistant_facts:
            events.append((
                "memory.assistant_only_facts_rejected",
                "warning",
                "Assistant-only profile memories rejected",
                {"count": len(rejected_assistant_facts)},
            ))
        repaired_preferences = memory_service.repair_legacy_response_length_preferences()
        if repaired_preferences:
            events.append((
                "memory.legacy_preference_repaired",
                "info",
                "Legacy response-length preferences repaired",
                {"count": len(repaired_preferences)},
            ))
        repaired_relationships = memory_service.repair_ambiguous_relationship_memories()
        if repaired_relationships:
            events.append((
                "memory.ambiguous_relationships_reviewed",
                "info",
                "Ambiguous relationship memories moved to review",
                {"count": len(repaired_relationships)},
            ))
        events.append((
            "memory.v17_repair",
            "info",
            "Canonical memory v17 repair checked",
            memory_service.repair_v17_canonical_memory(),
        ))
        events.append((
            "memory.v18_repair",
            "info",
            "Memory integrity v18 repair checked",
            memory_service.repair_v18_memory_integrity(),
        ))
        events.append((
            "memory.v19_repair",
            "info",
            "Autonomous memory v19 repair checked",
            memory_service.repair_v19_autonomous_memory(),
        ))
        expired = memory_service.expire_due_memories()
        if expired:
            events.append((
                "memory.temporal_expired",
                "info",
                "Expired temporal memories archived",
                {"count": expired},
            ))
        index_repair = memory_service.reindex()
        events.append((
            "memory.index_reconciled",
            "info" if index_repair.get("semantic_enabled") else "warning",
            "Rebuildable memory index reconciled with SQLite",
            index_repair,
        ))
        return events

    readiness: dict[str, Any] = {
        "phase": "starting",
        "text_chat": "loading",
        "stt": "loading" if settings.voice_preload_stt_model else "disabled",
        "tts": (
            "loading"
            if settings.voice_preload_tts_model and settings.voice_tts_enabled
            else "disabled"
        ),
        "vad": "fallback" if settings.voice_vad_provider == "silero" else "ready",
        "live_ready": False,
        "errors": [],
    }

    def update_readiness(
        component: str,
        status: str,
        error: str | None = None,
    ) -> None:
        readiness[component] = status
        if error:
            errors = readiness["errors"]
            if error not in errors:
                errors.append(error)
        readiness["live_ready"] = (
            readiness["text_chat"] == "ready"
            and readiness["stt"] == "ready"
            and readiness["tts"] == "ready"
            and readiness["vad"] in {"ready", "fallback"}
        )
        if readiness["text_chat"] == "failed":
            readiness["phase"] = "degraded"
        elif any(readiness[name] == "failed" for name in ("stt", "tts", "vad")):
            readiness["phase"] = "degraded"
        elif readiness["text_chat"] != "ready":
            readiness["phase"] = "starting"
        elif readiness["live_ready"]:
            readiness["phase"] = "ready"
        else:
            readiness["phase"] = "text_ready"

    async def run_storage_maintenance() -> None:
        """Defer repair, reindex, and cleanup until after text UI is usable."""
        try:
            removed = await asyncio.to_thread(voice_service.clear_tts_audio)
            clear_stale_uploads = getattr(voice_service, "clear_stale_uploads", None)
            stale_uploads = (
                await asyncio.to_thread(clear_stale_uploads)
                if clear_stale_uploads is not None
                else 0
            )
            if removed:
                logger.info("Generated WAV startup cleanup complete: removed=%s", removed)
            if stale_uploads:
                event_bus.publish(
                    "voice.stale_uploads_removed",
                    "info",
                    "Abandoned temporary voice uploads removed",
                    {"count": stale_uploads},
                )
            for event_type, level, message, metadata in await asyncio.to_thread(
                run_storage_repair
            ):
                event_bus.publish(event_type, level, message, metadata)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Deferred storage maintenance failed", exc_info=True)
            event_bus.publish(
                "backend.status",
                "warning",
                "Deferred storage maintenance failed; text chat remains available",
                {},
            )

    async def preload_stt() -> None:
        if not settings.voice_preload_stt_model:
            return
        try:
            await voice_service.preload_stt()
            update_readiness("stt", "ready")
            event_bus.publish(
                "voice.stt_preloaded",
                "info",
                "Voice STT model preloaded",
                {
                    "provider": settings.voice_stt_provider,
                    "model": settings.voice_stt_model,
                    "device": settings.voice_stt_device,
                    "threading": torch_threading or {},
                    **dict(getattr(voice_service.stt_provider, "metadata", {})),
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Voice STT preload failed", exc_info=True)
            update_readiness("stt", "failed", f"stt: {type(exc).__name__}: {exc}")
            event_bus.publish(
                "voice.stt_preload_failed",
                "warning",
                "Voice STT preload failed; first request will retry lazy load",
                {"provider": settings.voice_stt_provider, "model": settings.voice_stt_model},
            )

    async def preload_tts() -> None:
        if not settings.voice_preload_tts_model or not settings.voice_tts_enabled:
            return
        tts_metadata = dict(getattr(voice_service.tts_provider, "metadata", {}))
        tts_metadata.setdefault("provider", voice_service.tts_provider.name)
        event_bus.publish(
            "voice.tts_preloading_started",
            "info",
            "Voice TTS model preloading started",
            tts_metadata,
        )
        preload_started = time.perf_counter()
        try:
            await voice_service.preload_tts()
            duration_ms = int((time.perf_counter() - preload_started) * 1000)
            update_readiness("tts", "ready")
            event_bus.publish(
                "voice.tts_preloaded",
                "info",
                "Voice TTS model preloaded",
                {**tts_metadata, "duration_ms": duration_ms},
            )
            if getattr(voice_service.tts_provider, "warmup_enabled", False):
                event_bus.publish(
                    "voice.tts_warmed_up",
                    "info",
                    "Voice TTS model warmed up",
                    {**tts_metadata, "duration_ms": duration_ms},
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Voice TTS preload failed", exc_info=True)
            update_readiness("tts", "failed", f"tts: {type(exc).__name__}: {exc}")
            failed_metadata = dict(getattr(voice_service.tts_provider, "metadata", {}))
            failed_metadata.update({"error_type": type(exc).__name__, "error_message": str(exc)})
            event_bus.publish(
                "voice.tts_preload_failed",
                "warning",
                "Voice TTS preload failed; browser speech fallback remains available",
                failed_metadata,
            )

    async def preload_vad() -> None:
        if settings.voice_vad_provider != "silero":
            update_readiness("vad", "ready")
            return
        try:
            provider = await asyncio.to_thread(SileroVadProvider, vad_model_path)
            if provider.ready:
                voice_input_session_manager.set_vad_provider(provider)
                update_readiness("vad", "ready")
                event_bus.publish("voice.vad_ready", "info", "Silero VAD is ready", voice_input_session_manager.vad_status)
            else:
                reason = provider.error or "Silero VAD is unavailable"
                update_readiness("vad", "fallback", f"vad: {reason}")
                event_bus.publish("voice.vad_fallback", "warning", "Energy VAD fallback is active", {"reason": reason})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Silero VAD preload failed", exc_info=True)
            update_readiness("vad", "fallback", f"vad: {type(exc).__name__}: {exc}")
            event_bus.publish("voice.vad_fallback", "warning", "Energy VAD fallback is active", {"reason": str(exc)})

    async def preload_turn_detector() -> None:
        try:
            detector = await asyncio.to_thread(
                SmartTurnDetector,
                model_manager.path_for("smart-turn-v3.2"),
            )
            voice_input_session_manager.set_turn_detector(detector)
            if conversation_service is not None:
                conversation_service.bind_turn_detector(detector)
            if not detector.ready:
                event_bus.publish(
                    "voice.smart_turn_fallback",
                    "warning",
                    "Smart Turn fallback is active",
                    {"error": detector.error},
                )
                readiness["errors"].append(f"smart_turn: {detector.error}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Smart Turn preload failed", exc_info=True)
            readiness["errors"].append(f"smart_turn: {type(exc).__name__}: {exc}")

    async def preload_voice_runtime() -> None:
        nonlocal torch_threading
        async def configure_torch() -> None:
            nonlocal torch_threading
            try:
                torch_threading = await asyncio.to_thread(
                    configure_torch_threads,
                    settings.voice_torch_cpu_threads,
                    settings.voice_torch_interop_threads,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Voice Torch threading setup failed", exc_info=True)
                readiness["errors"].append(f"torch: {type(exc).__name__}: {exc}")

        # Keep all optional preparation off the critical startup path. The
        # thread policy runs alongside provider preparation; providers also
        # enforce their own bounded executors, so a slow model cannot starve
        # the event loop or text API.
        await asyncio.gather(
            configure_torch(),
            preload_stt(),
            preload_tts(),
            preload_vad(),
            preload_turn_detector(),
        )

    async def startup() -> None:
        nonlocal tts_audio_cleanup_task, storage_maintenance_task, voice_preload_task, avatar_start_task
        nonlocal summary_worker_task, semantic_sync_worker_task, memory_extraction_worker_task, reflection_worker_task, coding_worker_task

        try:
            if timeline_store is not None and settings.database_path.exists():
                with sqlite3.connect(settings.database_path) as migration_connection:
                    has_migrations = migration_connection.execute(
                        """
                        SELECT 1 FROM sqlite_master
                        WHERE type = 'table' AND name = 'schema_migrations'
                        """
                    ).fetchone()
                    latest_schema = (
                        migration_connection.execute(
                            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                        ).fetchone()[0]
                        if has_migrations
                        else 0
                    )
                    has_latest_schema = bool(
                        has_migrations
                        and migration_connection.execute(
                            "SELECT 1 FROM schema_migrations WHERE version = ?",
                            (LATEST_SCHEMA_VERSION,),
                        ).fetchone()
                    )
                if not has_latest_schema:
                    backup = await asyncio.to_thread(backup_service.create)
                    event_bus.publish(
                        "storage.pre_migration_backup",
                        "info",
                        f"Backup created before schema v{LATEST_SCHEMA_VERSION} migration",
                        {
                            "name": backup["name"],
                            "from_version": latest_schema,
                            "to_version": LATEST_SCHEMA_VERSION,
                        },
                    )
            await asyncio.to_thread(run_storage_migrations)
        except Exception:
            logger.critical("Storage initialization failed", exc_info=True)
            event_bus.publish(
                "backend.status",
                "critical",
                "Storage initialization failed",
                {},
            )
            raise

        update_readiness("text_chat", "ready")

        event_bus.publish(
            "backend.status",
            "info",
            "Backend startup complete",
            {"version": app.version},
        )
        logger.info("Backend text stack ready; voice preparation continues in background")

        storage_maintenance_task = asyncio.create_task(run_storage_maintenance())
        voice_preload_task = asyncio.create_task(preload_voice_runtime())

        async def start_avatar_after_ui() -> None:
            try:
                await avatar_service.start()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Avatar service startup failed", exc_info=True)

        avatar_start_task = asyncio.create_task(start_avatar_after_ui())
        tts_audio_cleanup_task = asyncio.create_task(cleanup_tts_audio_forever())
        if summary_worker is not None:
            summary_worker_task = asyncio.create_task(
                _supervise_worker("episode_summary", summarize_forever, event_bus.publish),
                name="worker:episode-summary",
            )
        if semantic_sync_worker is not None:
            semantic_sync_worker_task = asyncio.create_task(
                _supervise_worker("semantic_sync", sync_semantic_forever, event_bus.publish),
                name="worker:semantic-sync",
            )
        if memory_extraction_worker is not None:
            memory_extraction_worker_task = asyncio.create_task(
                _supervise_worker("memory_extraction", extract_memory_forever, event_bus.publish),
                name="worker:memory-extraction",
            )
        if character_state_service is not None:
            reflection_worker_task = asyncio.create_task(
                _supervise_worker("character_reflection", reflect_forever, event_bus.publish),
                name="worker:character-reflection",
            )
        coding_worker_task = asyncio.create_task(
            _supervise_worker("coding", run_coding_forever, event_bus.publish),
            name="worker:coding",
        )
        # Let zero-cost preload failures/events be observed by the first
        # request without waiting for model downloads or Torch import.
        await asyncio.sleep(0)

    async def shutdown() -> None:
        for task in (storage_maintenance_task, voice_preload_task, avatar_start_task):
            if task is not None and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5)
                except asyncio.TimeoutError:
                    task.cancel()
                    with contextlib.suppress(BaseException):
                        await task
                except Exception:
                    logger.warning("Deferred startup task ended with an error", exc_info=True)
        worker_tasks = tuple(
            task for task in (
                reflection_worker_task,
                coding_worker_task,
                summary_worker_task,
                semantic_sync_worker_task,
                memory_extraction_worker_task,
            )
            if task is not None
        )
        for task in worker_tasks:
            task.cancel()
        if worker_tasks:
            # Await every cancellation before closing worker dependencies. If
            # shutdown itself is cancelled, gather propagates CancelledError.
            results = await asyncio.gather(*worker_tasks, return_exceptions=True)
            for task, result in zip(worker_tasks, results, strict=True):
                if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError,
                ):
                    logger.warning(
                        "Background worker task %s failed during shutdown",
                        task.get_name(),
                        exc_info=(type(result), result, result.__traceback__),
                    )
        # Input sessions may still own endpoint/STT callbacks that call into
        # conversation and voice services. Drain them before those dependencies.
        await voice_input_session_manager.close()
        if conversation_service is not None:
            await conversation_service.close()
        if timeline_store is not None:
            await asyncio.to_thread(timeline_store.close_current_episode, "application_shutdown")
        if summary_worker is not None:
            try:
                await asyncio.wait_for(summary_worker.run_once(), timeout=1)
            except Exception:
                logger.warning("Bounded shutdown summary pass did not complete", exc_info=True)
        if tts_audio_cleanup_task is not None:
            tts_audio_cleanup_task.cancel()
            try:
                await tts_audio_cleanup_task
            except asyncio.CancelledError:
                pass
        await voice_session_manager.close()
        await speech_orchestrator.close()
        await avatar_service.close()
        voice_service_close = getattr(voice_service, "close", None)
        if voice_service_close is not None:
            await voice_service_close()
        await close_shared_clients()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Same ordering contract the deprecated on_event handlers had: a failed
        # startup propagates and shutdown does not run.
        await startup()
        try:
            yield
        finally:
            await shutdown()

    app.router.lifespan_context = lifespan

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readiness")
    def readiness_status() -> dict[str, Any]:
        return {
            "phase": readiness["phase"],
            "text_chat": readiness["text_chat"],
            "stt": readiness["stt"],
            "tts": readiness["tts"],
            "vad": readiness["vad"],
            "live_ready": readiness["live_ready"],
            "errors": list(readiness["errors"]),
        }

    app.state.settings = settings
    app.state.history = history
    app.state.timeline_store = timeline_store
    app.state.turn_coordinator = turn_coordinator
    app.state.context_manager = context_manager
    app.state.memory_service = memory_service
    app.state.conversation_service = conversation_service
    app.state.character_state_service = character_state_service
    app.state.event_bus = event_bus
    app.state.runtime_settings = runtime_settings
    app.state.runtime_settings_store = runtime_settings_store
    app.state.coding_agent_service = coding_agent_service
    app.state.coding_bridge = coding_bridge
    app.state.model_manager = model_manager
    app.state.backup_service = backup_service
    app.state.voice_service = voice_service
    app.state.voice_session_manager = voice_session_manager
    app.state.voice_input_session_manager = voice_input_session_manager
    app.state.interrupt_voice_session = interrupt_voice_session
    app.state.avatar_service = avatar_service
    app.state.speech_orchestrator = speech_orchestrator
    app.state.llm_telemetry = llm_telemetry
    app.include_router(chat_router)
    app.include_router(avatar_router)
    app.include_router(events_router)
    app.include_router(settings_router)
    app.include_router(status_router)
    app.include_router(voice_router)
    app.include_router(timeline_router)
    app.include_router(episodes_router)
    app.include_router(context_debug_router)
    app.include_router(llm_diagnostics_router)
    app.include_router(memory_router)
    app.include_router(models_router)
    app.include_router(maintenance_router)
    app.include_router(conversation_router)
    app.include_router(coding_router)
    app.include_router(websocket_router)
    return app


app = create_app()
