import logging

from fastapi import APIRouter, HTTPException, Request, status

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
    await manager.start(
        session_id=payload.session_id,
        utterance_id=utterance_id,
        transcript=payload.message,
        language=runtime_settings.voice_language,
        voice=voice,
        agent=agent,
        input_mode="text",
    )
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
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
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
        result = await agent.handle_user_message(payload.session_id, payload.message)
        result["memory_updates"] = agent.last_memory_updates
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
