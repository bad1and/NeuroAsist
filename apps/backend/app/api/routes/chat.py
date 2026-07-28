import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.api.routes.conversation import require_active_session
from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import LLMProviderError
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
from apps.backend.app.schemas.chat import ChatRequest, ChatResponse
from apps.backend.app.schemas.voice import VoiceLiveResponse
from apps.backend.app.voice.style import resolve_turn_voice_style

from uuid import uuid4

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat/live", response_model=VoiceLiveResponse)
async def live_chat(payload: ChatRequest, request: Request) -> VoiceLiveResponse:
    """Stream a typed message through the same LLM/TTS path as live voice.

    The browser sends text directly, so this deliberately does not invoke STT.
    A connected voice socket is still required because it carries text deltas,
    metadata and audio segments back to the desktop client.
    """
    require_active_session(request, payload.session_id)
    settings = request.app.state.settings
    if not settings.voice_tts_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Live text requires backend TTS to be enabled",
        )
    manager = request.app.state.voice_session_manager
    if not manager.connected(payload.session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice WebSocket must be connected before live request",
        )

    runtime_settings = request.app.state.runtime_settings
    event_bus = request.app.state.event_bus
    voice_request_id = uuid4().hex
    utterance_id = uuid4().hex
    provider = DeepSeekProvider(settings)
    agent = CharacterAgent(
        llm_provider=provider,
        history=request.app.state.history,
        history_limit=settings.chat_history_limit,
        event_publisher=event_bus.publish,
        context_manager=request.app.state.context_manager,
        memory_service=request.app.state.memory_service,
        persona_name=runtime_settings.personality,
    )
    voice = request.app.state.voice_service.resolve_tts_voice(
        runtime_settings.voice_language,
        runtime_settings.voice_tts_voice,
    )
    source_message = None
    lease = None
    coordinator = getattr(request.app.state, "turn_coordinator", None)
    if coordinator is not None:
        try:
            accepted = await coordinator.accept_user_turn(
                session_id=payload.session_id, content=payload.message, input_mode="text",
                client_message_id=payload.client_message_id, utterance_id=utterance_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        source_message = accepted.message
        if not accepted.created:
            existing = request.app.state.timeline_store.assistant_for_user(source_message.id)
            return VoiceLiveResponse(
                session_id=payload.session_id, utterance_id=utterance_id,
                voice_request_id=voice_request_id, transcript=payload.message,
                message_id=source_message.id, turn_id=source_message.turn_id,
                status=existing.status if existing is not None else "streaming",
            )
        lease = await coordinator.begin_assistant(accepted, commit_policy="generated_text")
    else:
        timeline_store = getattr(request.app.state, "timeline_store", None)
        if timeline_store is not None:
            source_message, _ = timeline_store.append_message(
                role="user", content=payload.message, input_mode="text",
                utterance_id=utterance_id, metadata={"legacy_session_id": payload.session_id},
            )
    async def complete_live_assistant(reply: str) -> None:
        if coordinator is None or lease is None:
            return
        assistant_message = await coordinator.complete_assistant(payload.session_id, lease, reply)
        if request.app.state.memory_service is not None:
            request.app.state.memory_service.schedule_extraction(assistant_message)

    async def interrupt_live_assistant(prefix: str) -> None:
        if coordinator is not None and lease is not None:
            await coordinator.interrupt_assistant(payload.session_id, lease, prefix)

    task = await manager.start(
        session_id=payload.session_id,
        utterance_id=utterance_id,
        transcript=payload.message,
        language=runtime_settings.voice_language,
        voice=voice,
        agent=agent,
        input_mode="text",
        source_message=source_message,
        persist_reply=False if lease is not None else True,
        on_assistant_completed=complete_live_assistant if lease is not None else None,
        on_assistant_interrupted=interrupt_live_assistant if lease is not None else None,
    )
    if coordinator is not None and lease is not None:
        coordinator.register_generation_task(lease, task)
    event_bus.publish(
        "chat.live_started",
        "info",
        "Live text response started",
        {
            "session_id": payload.session_id,
            "utterance_id": utterance_id,
            "voice_request_id": voice_request_id,
            "message_length": len(payload.message),
        },
    )
    return VoiceLiveResponse(
        session_id=payload.session_id,
        utterance_id=utterance_id,
        voice_request_id=voice_request_id,
        transcript=payload.message,
        message_id=source_message.id if source_message is not None else None,
        turn_id=source_message.turn_id if source_message is not None else None,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    require_active_session(request, payload.session_id)
    settings = request.app.state.settings
    history = request.app.state.history
    event_bus = request.app.state.event_bus
    event_bus.publish(
        "chat.started",
        "info",
        "Chat request started",
        {
            "session_id": payload.session_id,
            "message_length": len(payload.message),
        },
    )

    lease = None
    accepted = None
    try:
        provider = DeepSeekProvider(settings)
        agent = CharacterAgent(
            llm_provider=provider,
            history=history,
            history_limit=settings.chat_history_limit,
            event_publisher=event_bus.publish,
            context_manager=request.app.state.context_manager,
            memory_service=request.app.state.memory_service,
            persona_name=request.app.state.runtime_settings.personality,
        )
        coordinator = getattr(request.app.state, "turn_coordinator", None)
        if coordinator is not None:
            try:
                accepted = await coordinator.accept_user_turn(
                    session_id=payload.session_id,
                    content=payload.message,
                    input_mode="text",
                    client_message_id=payload.client_message_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
            if not accepted.created:
                previous = request.app.state.timeline_store.assistant_for_user(accepted.user_message_id)
                if previous is not None and previous.status == "completed":
                    return ChatResponse(
                        reply=previous.effective_content,
                        message_id=accepted.user_message_id,
                        assistant_message_id=previous.id,
                        turn_id=accepted.turn_id,
                        generation=accepted.generation,
                    )
            lease = await coordinator.begin_assistant(accepted)
            coordinator.register_generation_task(lease)
            result = await agent.handle_user_message(
                payload.session_id, payload.message, source_message=accepted.message, persist_reply=False,
            )
            assistant_message = await coordinator.complete_assistant(payload.session_id, lease, result["reply"])
            if request.app.state.memory_service is not None:
                request.app.state.memory_service.schedule_extraction(assistant_message)
            result.update({
                "message_id": accepted.user_message_id,
                "assistant_message_id": assistant_message.id,
                "turn_id": accepted.turn_id,
                "generation": accepted.generation,
            })
        else:
            result = await agent.handle_user_message(payload.session_id, payload.message)
        result["memory_updates"] = agent.last_memory_updates
    except asyncio.CancelledError:
        if lease is not None:
            await request.app.state.turn_coordinator.interrupt_assistant(payload.session_id, lease)
        raise
    except HTTPException:
        raise
    except ValueError as exc:
        logger.error(
            "Chat request failed: session_id=%s message_length=%s",
            payload.session_id,
            len(payload.message),
            exc_info=True,
        )
        event_bus.publish(
            "chat.failed",
            "error",
            "Chat request failed",
            {
                "session_id": payload.session_id,
                "message_length": len(payload.message),
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except LLMProviderError as exc:
        if lease is not None:
            await request.app.state.turn_coordinator.fail_assistant(payload.session_id, lease)
        logger.error(
            "LLM provider failed during chat request: session_id=%s message_length=%s",
            payload.session_id,
            len(payload.message),
            exc_info=True,
        )
        event_bus.publish(
            "llm.error",
            "error",
            "LLM provider failed during chat request",
            {
                "session_id": payload.session_id,
                "message_length": len(payload.message),
                "error_type": type(exc).__name__,
            },
        )
        event_bus.publish(
            "chat.failed",
            "error",
            "Chat request failed",
            {
                "session_id": payload.session_id,
                "message_length": len(payload.message),
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        if lease is not None:
            await request.app.state.turn_coordinator.fail_assistant(payload.session_id, lease)
        logger.exception(
            "Unexpected /chat failure: session_id=%s message_length=%s",
            payload.session_id,
            len(payload.message),
        )
        event_bus.publish(
            "chat.failed",
            "critical",
            "Unexpected chat failure",
            {
                "session_id": payload.session_id,
                "message_length": len(payload.message),
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal chat error",
        ) from exc

    logger.info(
        "Chat request complete: session_id=%s message_length=%s",
        payload.session_id,
        len(payload.message),
    )
    event_bus.publish(
        "chat.completed",
        "info",
        "Chat request completed",
        {
            "session_id": payload.session_id,
            "reply_length": len(result["reply"]),
            "emotion": result["emotion"],
            "intent": result["intent"],
        },
    )
    if agent.last_turn is not None:
        event_bus.publish(
            "character.metadata",
            "info",
            "Character metadata resolved",
            {"session_id": payload.session_id, "metadata": agent.last_turn.metadata_frame()},
        )
    response = ChatResponse(**result)
    # Text chat is independently speakable.  Avatar availability only affects
    # animation delivery inside the orchestrator, not whether audio is made.
    if settings.voice_tts_enabled and result["reply"].strip():
        voice = request.app.state.voice_service.resolve_tts_voice(
            request.app.state.runtime_settings.voice_language,
            request.app.state.runtime_settings.voice_tts_voice,
        )
        orchestrator = request.app.state.speech_orchestrator
        orchestrator.bind_runtime(request.app.state.voice_service, settings)
        response.voice_request_id = orchestrator.enqueue(
            session_id=payload.session_id,
            voice_request_id=uuid4().hex,
            reply=result["reply"],
            emotion=result["emotion"],
            intent=result["intent"],
            gesture=result.get("gesture", "auto"),
            voice=voice,
            style=resolve_turn_voice_style(getattr(request.app.state, "voice_tts_style", "auto"), agent.last_turn),
        )
        response.tts_status = "queued"
    return response
