import asyncio

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(prefix="/conversation", tags=["conversation"])


def require_active_session(request: Request, session_id: str) -> None:
    store = getattr(request.app.state, "timeline_store", None)
    if store is None:
        return
    active_session_id = store.active_session_id()
    if active_session_id is not None and session_id != active_session_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is no longer active")


@router.post("/session/reset")
async def reset_session(request: Request) -> dict[str, object]:
    store = getattr(request.app.state, "timeline_store", None)
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Timeline V2 is disabled")
    previous_session_id = store.active_session_id()
    if previous_session_id:
        coordinator = getattr(request.app.state, "turn_coordinator", None)
        if coordinator is not None:
            await coordinator.cancel_session(previous_session_id)
        await request.app.state.voice_session_manager.cancel(previous_session_id, notify=False)
        await request.app.state.speech_orchestrator.cancel_session(previous_session_id)
        voice_input = getattr(request.app.state, "voice_input_session_manager", None)
        if voice_input is not None:
            await voice_input.close_session(previous_session_id)
        service = getattr(request.app.state, "conversation_service", None)
        if service is not None:
            await service.close_session(previous_session_id)
    result = await asyncio.to_thread(store.reset_session)
    request.app.state.event_bus.publish(
        "conversation.session_reset", "warning", "Conversation session reset", result,
    )
    return result


@router.get("/debug/{session_id}")
def conversation_debug(session_id: str, request: Request) -> dict[str, object]:
    require_active_session(request, session_id)
    if not request.app.state.settings.conversation_diagnostics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    service = getattr(request.app.state, "conversation_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Conversation service unavailable")
    return service.debug(session_id)
