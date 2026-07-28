import asyncio
import logging
import time
from uuid import uuid4
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from apps.backend.app.api.routes.conversation import require_active_session
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import LLMProviderError
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
from apps.backend.app.schemas.voice import (
    VoiceChatResponse,
    VoiceInterruptRequest,
    VoiceLiveResponse,
    VoiceProviderStats,
    VoiceTTSStatusResponse,
)
from apps.backend.app.voice.style import resolve_turn_voice_style

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/voice/interrupt")
async def interrupt_voice(payload: VoiceInterruptRequest, request: Request) -> dict[str, object]:
    """Stop all current speech for a session as soon as user speech begins."""
    require_active_session(request, payload.session_id)
    interrupt = getattr(request.app.state, "interrupt_voice_session", None)
    if callable(interrupt):
        cancelled = await interrupt(payload.session_id, payload.utterance_id)
    else:
        await request.app.state.voice_session_manager.cancel(payload.session_id, payload.utterance_id)
        cancelled = {"live": 0, "batch": 0}
    return {"status": "cancelled", "session_id": payload.session_id, "cancelled": cancelled}


@router.post("/voice/chat", response_model=VoiceChatResponse | VoiceLiveResponse)
async def voice_chat(
    request: Request,
    audio: UploadFile = File(...),
    session_id: str = Form(default="default"),
    language: str = Form(default="auto"),
    live: bool = Form(default=False),
    client_message_id: str | None = Form(default=None),
    client_end_of_speech_unix_ms: int | None = Form(default=None),
) -> VoiceChatResponse | VoiceLiveResponse:
    require_active_session(request, session_id)
    request_started = time.perf_counter()
    end_of_speech_age_ms = (
        max(0, int(time.time() * 1000) - client_end_of_speech_unix_ms)
        if client_end_of_speech_unix_ms is not None
        else None
    )
    voice_request_id = uuid4().hex
    settings = request.app.state.settings
    history = request.app.state.history
    event_bus = request.app.state.event_bus
    runtime_settings = request.app.state.runtime_settings
    voice_service = request.app.state.voice_service
    lease = None

    selected_language = language if language != "auto" else runtime_settings.voice_language
    if selected_language not in {"auto", "ru", "en"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported voice language",
        )

    upload_save_started = time.perf_counter()
    upload_path = await voice_service.save_upload(audio)
    upload_save_ms = int((time.perf_counter() - upload_save_started) * 1000)
    event_bus.publish(
        "voice.upload_received",
        "info",
        "Voice upload received",
        {
            "session_id": session_id,
            "language": selected_language,
            "duration_ms": upload_save_ms,
            "pipeline_elapsed_ms": int((time.perf_counter() - request_started) * 1000),
            "end_of_speech_to_upload_ms": end_of_speech_age_ms,
        },
    )

    try:
        event_bus.publish(
            "voice.transcribing_started",
            "info",
            "Voice transcription started",
            {"session_id": session_id},
        )
        stt_result = await asyncio.wait_for(
            voice_service.stt_provider.transcribe(upload_path, selected_language),
            timeout=settings.voice_stt_timeout_seconds,
        )
        if not stt_result.text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not transcribe speech",
            )
        event_bus.publish(
            "voice.transcribing_finished",
            "info",
            "Voice transcription finished",
            {
                "session_id": session_id,
                "language": stt_result.language,
                "duration_ms": stt_result.duration_ms,
                "pipeline_elapsed_ms": int((time.perf_counter() - request_started) * 1000),
                "provider": stt_result.provider,
                "model": stt_result.model,
            },
        )

        provider = DeepSeekProvider(settings)
        agent = CharacterAgent(
            llm_provider=provider,
            history=history,
            history_limit=settings.chat_history_limit,
            event_publisher=event_bus.publish,
            context_manager=request.app.state.context_manager,
            memory_service=request.app.state.memory_service,
            persona_name=runtime_settings.personality,
        )
        voice = voice_service.resolve_tts_voice(
            stt_result.language,
            runtime_settings.voice_tts_voice,
        )
        utterance_id = uuid4().hex if live else None
        coordinator = getattr(request.app.state, "turn_coordinator", None)
        accepted = None
        if coordinator is not None:
            try:
                accepted = await coordinator.accept_user_turn(
                    session_id=session_id, content=stt_result.text, input_mode="voice",
                    client_message_id=client_message_id, utterance_id=utterance_id, language=stt_result.language,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if live:
            manager = request.app.state.voice_session_manager
            if not manager.connected(session_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Voice WebSocket must be connected before live request",
                )
            if accepted is not None and not accepted.created:
                existing = request.app.state.timeline_store.assistant_for_user(accepted.user_message_id)
                return VoiceLiveResponse(
                    session_id=session_id, utterance_id=utterance_id, voice_request_id=voice_request_id,
                    transcript=stt_result.text, message_id=accepted.user_message_id, turn_id=accepted.turn_id,
                    status=existing.status if existing is not None else "streaming",
                )
            live_lease = await coordinator.begin_assistant(accepted, commit_policy="generated_text") if accepted is not None else None

            async def complete_live_assistant(reply: str) -> None:
                if live_lease is None:
                    return
                assistant_message = await coordinator.complete_assistant(session_id, live_lease, reply)
                if request.app.state.memory_service is not None:
                    request.app.state.memory_service.schedule_extraction(assistant_message)

            async def interrupt_live_assistant(prefix: str) -> None:
                if live_lease is not None:
                    await coordinator.interrupt_assistant(session_id, live_lease, prefix)

            task = await manager.start(
                session_id=session_id,
                utterance_id=utterance_id,
                transcript=stt_result.text,
                language=stt_result.language,
                voice=voice,
                agent=agent,
                style_override=getattr(request.app.state, "voice_tts_style", "auto"),
                source_message=accepted.message if accepted is not None else None,
                persist_reply=False if live_lease is not None else None,
                on_assistant_completed=complete_live_assistant if live_lease is not None else None,
                on_assistant_interrupted=interrupt_live_assistant if live_lease is not None else None,
            )
            if live_lease is not None:
                coordinator.register_generation_task(live_lease, task)
            event_bus.publish(
                "voice.live_started",
                "info",
                "Live voice response started",
                {
                    "session_id": session_id,
                    "utterance_id": utterance_id,
                    "voice_request_id": voice_request_id,
                    "stt_ms": stt_result.duration_ms,
                    "pipeline_elapsed_ms": int((time.perf_counter() - request_started) * 1000),
                },
            )
            return VoiceLiveResponse(
                session_id=session_id,
                utterance_id=utterance_id,
                voice_request_id=voice_request_id,
                transcript=stt_result.text,
            )
        event_bus.publish(
            "chat.started",
            "info",
            "Voice chat request started",
            {"session_id": session_id, "message_length": len(stt_result.text)},
        )
        llm_started = time.perf_counter()
        if accepted is not None:
            if not accepted.created:
                previous = request.app.state.timeline_store.assistant_for_user(accepted.user_message_id)
                if previous is not None and previous.status == "completed":
                    result = {"reply": previous.effective_content, "emotion": "neutral", "intent": "casual_chat"}
                else:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Voice turn is already generating")
            else:
                lease = await coordinator.begin_assistant(accepted)
                coordinator.register_generation_task(lease)
                result = await asyncio.wait_for(
                    agent.handle_user_message(
                        session_id, stt_result.text, input_mode="voice",
                        source_message=accepted.message, persist_reply=False,
                    ),
                    timeout=settings.voice_llm_timeout_seconds,
                )
                assistant_message = await coordinator.complete_assistant(session_id, lease, result["reply"])
                if request.app.state.memory_service is not None:
                    request.app.state.memory_service.schedule_extraction(assistant_message)
        else:
            result = await asyncio.wait_for(
                agent.handle_user_message(session_id, stt_result.text, input_mode="voice"),
                timeout=settings.voice_llm_timeout_seconds,
            )
        result["memory_updates"] = agent.last_memory_updates
        llm_duration_ms = int((time.perf_counter() - llm_started) * 1000)
        tts_status = "disabled"
        if settings.voice_tts_enabled and result["reply"].strip():
            tts_status = "queued"
            orchestrator = request.app.state.speech_orchestrator
            orchestrator.bind_runtime(voice_service, settings)
            orchestrator.enqueue(
                session_id=session_id, voice_request_id=voice_request_id, reply=result["reply"],
                emotion=result["emotion"], intent=result["intent"],
                gesture=result.get("gesture", "auto"), voice=voice,
                style=resolve_turn_voice_style(getattr(request.app.state, "voice_tts_style", "auto"), agent.last_turn),
            )
        elif not result["reply"].strip():
            tts_status = "skipped"
            voice_service.set_tts_job(
                voice_request_id,
                {
                    "status": "skipped",
                    "audio_url": None,
                    "voice": voice if settings.voice_tts_enabled else None,
                },
            )
        else:
            voice_service.set_tts_job(
                voice_request_id,
                {
                    "status": "disabled",
                    "audio_url": None,
                    "voice": None,
                },
            )

        event_bus.publish(
            "voice.completed",
            "info",
            "Voice chat request completed",
            {
                "session_id": session_id,
                "voice_request_id": voice_request_id,
                "upload_save_ms": upload_save_ms,
                "stt_ms": stt_result.duration_ms,
                "llm_ms": llm_duration_ms,
                "tts_status": tts_status,
                "total_ms": int((time.perf_counter() - request_started) * 1000),
            },
        )
        if agent.last_turn is not None:
            event_bus.publish(
                "character.metadata",
                "info",
                "Character metadata resolved",
                {"session_id": session_id, "metadata": agent.last_turn.metadata_frame()},
            )
    except HTTPException:
        if lease is not None:
            await coordinator.fail_assistant(session_id, lease)
        event_bus.publish(
            "voice.error",
            "error",
            "Voice request failed",
            {"session_id": session_id},
        )
        raise
    except LLMProviderError as exc:
        if lease is not None:
            await coordinator.fail_assistant(session_id, lease)
        logger.error("LLM provider failed during voice request", exc_info=True)
        event_bus.publish(
            "voice.error",
            "error",
            "LLM provider failed during voice request",
            {"session_id": session_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except TimeoutError as exc:
        if lease is not None:
            await coordinator.interrupt_assistant(session_id, lease)
        logger.error("Voice request timed out", exc_info=True)
        event_bus.publish(
            "voice.error",
            "error",
            "Voice request timed out",
            {"session_id": session_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Voice request timed out",
        ) from exc
    except Exception as exc:
        if lease is not None:
            await coordinator.fail_assistant(session_id, lease)
        logger.exception("Unexpected voice request failure")
        event_bus.publish(
            "voice.error",
            "error",
            "Voice request failed",
            {"session_id": session_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal voice error",
        ) from exc
    finally:
        voice_service.cleanup_upload(upload_path)

    return VoiceChatResponse(
        voice_request_id=voice_request_id,
        transcript=stt_result.text,
        reply=result["reply"],
        emotion=result["emotion"],
        intent=result["intent"],
        reply_audio_url=None,
        tts_status=tts_status,
        stt=VoiceProviderStats(
            provider=stt_result.provider,
            model=stt_result.model,
            language=stt_result.language,
            duration_ms=stt_result.duration_ms,
        ),
        tts=VoiceProviderStats(
            provider=settings.voice_tts_provider if settings.voice_tts_enabled else "disabled",
            voice=voice if settings.voice_tts_enabled else None,
            duration_ms=0,
        ),
        memory_updates=result.get("memory_updates", []),
    )


@router.get("/voice/audio/{audio_id}")
def get_voice_audio(audio_id: str, request: Request) -> FileResponse:
    voice_service = request.app.state.voice_service
    path = voice_service.resolve_audio_path(audio_id)
    media_type = "audio/wav" if path.suffix == ".wav" else "audio/mpeg"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/voice/tts/{voice_request_id}", response_model=VoiceTTSStatusResponse)
def get_voice_tts_status(voice_request_id: str, request: Request) -> VoiceTTSStatusResponse:
    voice_service = request.app.state.voice_service
    job = voice_service.get_tts_job(voice_request_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice TTS job not found",
        )
    return VoiceTTSStatusResponse.model_validate(job)

