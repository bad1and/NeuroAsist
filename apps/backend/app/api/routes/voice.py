from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from apps.backend.app.api.routes.conversation import require_active_session
from apps.backend.app.schemas.voice import VoiceInterruptRequest, VoiceTTSStatusResponse

router = APIRouter()


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
