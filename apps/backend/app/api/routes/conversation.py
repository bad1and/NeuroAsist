from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(prefix="/conversation", tags=["conversation"])


@router.get("/debug/{session_id}")
def conversation_debug(session_id: str, request: Request) -> dict[str, object]:
    if not request.app.state.settings.conversation_diagnostics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    service = getattr(request.app.state, "conversation_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Conversation service unavailable")
    return service.debug(session_id)
