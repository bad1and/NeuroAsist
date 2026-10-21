from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from apps.backend.app.api.routes.conversation import require_active_session_async
from apps.backend.app.schemas.voice import VoiceInterruptRequest, VoiceTTSStatusResponse

router = APIRouter()


@router.post("/voice/preview")
async def preview_voice(request: Request):
    """A fixed, local test phrase; never enters conversation or memory."""
    import asyncio
    from starlette.background import BackgroundTask

    lock = getattr(request.app.state, "voice_preview_lock", None)
    if lock is None:
        lock = request.app.state.voice_preview_lock = asyncio.Lock()
    if lock.locked():
        raise HTTPException(429, "Проба голоса уже готовится")
    service = request.app.state.voice_service
    runtime = request.app.state.runtime_settings
    path = service.next_tts_path("preview")
    try:
        async with lock:
            voice = service.resolve_tts_voice(runtime.voice_language, runtime.voice_tts_voice)
            result = await asyncio.wait_for(service.tts_provider.synthesize(
                "Привет! Это проверка голоса Ирис. Если ты меня слышишь, звук настроен.",
                voice, path, style=getattr(request.app.state, "voice_tts_style", "auto")), timeout=45)
        return FileResponse(result.audio_path, media_type="audio/wav", background=BackgroundTask(result.audio_path.unlink, missing_ok=True))
    except asyncio.TimeoutError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(504, "Голос не успел подготовиться. Проверьте локальную модель.") from exc
    except asyncio.CancelledError:
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(503, "Проба голоса недоступна. Проверьте модель синтеза речи.") from exc


@router.post("/voice/interrupt")
async def interrupt_voice(payload: VoiceInterruptRequest, request: Request) -> dict[str, object]:
    """Stop all current speech for a session as soon as user speech begins."""
    await require_active_session_async(request, payload.session_id)
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
