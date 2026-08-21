import asyncio

from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.api.routes.settings import _commit_runtime_settings_patch
from apps.backend.app.avatar.schemas import (
    AvatarStatusResponse,
    AvatarOverlayPatch,
    OverlayPayload,
    AvatarStopRequest,
    AvatarTestEmotionRequest,
    AvatarTestGestureRequest,
    AvatarTestSpeakRequest,
)
from apps.backend.app.voice.style import coerce_voice_style

router = APIRouter(prefix="/avatar", tags=["avatar"])


@router.get("/status", response_model=AvatarStatusResponse)
async def avatar_status(request: Request) -> AvatarStatusResponse:
    return await request.app.state.avatar_service.status()


def _overlay_from_runtime(runtime_settings) -> OverlayPayload:
    return OverlayPayload(
        visible=runtime_settings.avatar_overlay_visible,
        always_on_top=runtime_settings.avatar_overlay_always_on_top,
        locked=runtime_settings.avatar_overlay_locked,
        scale=runtime_settings.avatar_overlay_scale,
        monitor=runtime_settings.avatar_overlay_monitor,
        x=runtime_settings.avatar_overlay_x,
        y=runtime_settings.avatar_overlay_y,
        width=runtime_settings.avatar_overlay_width,
        height=runtime_settings.avatar_overlay_height,
    )


@router.get("/overlay", response_model=OverlayPayload)
async def avatar_overlay(request: Request) -> OverlayPayload:
    return _overlay_from_runtime(request.app.state.runtime_settings)


@router.put("/overlay", response_model=OverlayPayload)
async def update_avatar_overlay(payload: AvatarOverlayPatch, request: Request) -> OverlayPayload:
    runtime_settings = request.app.state.runtime_settings
    changes = {
        f"avatar_overlay_{field}": value
        for field, value in payload.model_dump(exclude_none=True).items()
    }
    try:
        await asyncio.to_thread(
            _commit_runtime_settings_patch,
            request.app.state.runtime_settings_store,
            runtime_settings,
            changes,
        )
    except OSError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not persist avatar overlay settings") from error
    overlay = _overlay_from_runtime(runtime_settings)
    result = await request.app.state.avatar_service.configure_overlay(overlay)
    request.app.state.event_bus.publish("avatar.overlay_updated", "info", "Avatar overlay settings updated", {**overlay.model_dump(), "sent": result.sent})
    return overlay


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
        gesture=payload.gesture,
        gesture_intensity=payload.gesture_intensity,
        voice=voice,
        style=coerce_voice_style(getattr(request.app.state, "voice_tts_style", "auto")),
        interrupt=payload.interrupt,
    )
    return {"voice_request_id": job_id, "status": "queued"}


@router.post("/test/emotion")
async def avatar_test_emotion(payload: AvatarTestEmotionRequest, request: Request) -> dict[str, int | bool]:
    result = await request.app.state.avatar_service.set_emotion(
        session_id=payload.session_id, emotion=payload.emotion, intensity=payload.intensity
    )
    return {"sent": result.sent, "skipped": result.skipped}


@router.post("/test/gesture")
async def avatar_test_gesture(payload: AvatarTestGestureRequest, request: Request) -> dict[str, int | bool | str]:
    result = await request.app.state.avatar_service.gesture(
        session_id=payload.session_id,
        gesture=payload.gesture,
        intensity=payload.intensity,
        interrupt=payload.interrupt,
    )
    return {"gesture": payload.gesture, "sent": result.sent, "skipped": result.skipped}


@router.post("/stop")
async def avatar_stop(payload: AvatarStopRequest, request: Request) -> dict[str, int | bool]:
    result = await request.app.state.avatar_service.stop(
        session_id=payload.session_id, utterance_id=payload.utterance_id
    )
    return {"sent": result.sent, "skipped": result.skipped}
