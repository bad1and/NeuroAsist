from fastapi import APIRouter, Request, status

from apps.backend.app.avatar.schemas import (
    AvatarStatusResponse,
    AvatarStopRequest,
    AvatarTestEmotionRequest,
    AvatarTestSpeakRequest,
)

router = APIRouter(prefix="/avatar", tags=["avatar"])


@router.get("/status", response_model=AvatarStatusResponse)
async def avatar_status(request: Request) -> AvatarStatusResponse:
    return await request.app.state.avatar_service.status()


@router.post("/test/speak", status_code=status.HTTP_202_ACCEPTED)
async def avatar_test_speak(payload: AvatarTestSpeakRequest, request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    runtime_settings = request.app.state.runtime_settings
    voice = request.app.state.voice_service.resolve_tts_voice(
        runtime_settings.voice_language, runtime_settings.voice_tts_voice
    )
    orchestrator = request.app.state.speech_orchestrator
    orchestrator.bind_runtime(request.app.state.voice_service, settings)
    job_id = orchestrator.enqueue(
        session_id=payload.session_id,
        reply=payload.text,
        emotion=payload.emotion,
        intent=payload.intent,
        voice=voice,
        interrupt=payload.interrupt,
    )
    return {"voice_request_id": job_id, "status": "queued"}


@router.post("/test/emotion")
async def avatar_test_emotion(payload: AvatarTestEmotionRequest, request: Request) -> dict[str, int | bool]:
    result = await request.app.state.avatar_service.set_emotion(
        session_id=payload.session_id, emotion=payload.emotion, intensity=payload.intensity
    )
    return {"sent": result.sent, "skipped": result.skipped}


@router.post("/stop")
async def avatar_stop(payload: AvatarStopRequest, request: Request) -> dict[str, int | bool]:
    result = await request.app.state.avatar_service.stop(
        session_id=payload.session_id, utterance_id=payload.utterance_id
    )
    return {"sent": result.sent, "skipped": result.skipped}
