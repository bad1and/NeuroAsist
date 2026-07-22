from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.schemas.settings import (
    PublicSettingsResponse,
    RuntimeSettingsPatch,
)

router = APIRouter()
AVAILABLE_PERSONALITIES = ["default"]
AVAILABLE_VOICE_LANGUAGES = ["auto", "ru", "en"]
MIN_PLAYBACK_RATE = 0.75
MAX_PLAYBACK_RATE = 1.25
MIN_PREBUFFER_SEGMENTS = 1
MAX_PREBUFFER_SEGMENTS = 4
MIN_PREBUFFER_MS = 0
MAX_PREBUFFER_MS = 1500
MEMORY_MODES = {"off", "balanced", "automatic", "ask"}


def _available_tts_voices(request: Request) -> list[str]:
    voice_service = request.app.state.voice_service
    return voice_service.available_tts_voices()


@router.get("/settings/public", response_model=PublicSettingsResponse)
def get_public_settings(request: Request) -> PublicSettingsResponse:
    settings = request.app.state.settings
    runtime_settings = request.app.state.runtime_settings
    tts_provider = request.app.state.voice_service.tts_provider
    tts_metadata = dict(getattr(tts_provider, "metadata", {}))

    return PublicSettingsResponse(
        provider="deepseek",
        model=settings.deepseek_model,
        personality=runtime_settings.personality,
        voice_language=runtime_settings.voice_language,
        voice_stt_model=settings.voice_stt_model,
        voice_tts_enabled=settings.voice_tts_enabled,
        voice_tts_provider=str(tts_metadata.get("provider", tts_provider.name)),
        voice_tts_model=tts_metadata.get("model"),
        voice_tts_device=tts_metadata.get("device"),
        voice_tts_fallback_active=bool(tts_metadata.get("fallback_active", False)),
        avatar_enabled=settings.avatar_enabled,
        voice_tts_voice=runtime_settings.voice_tts_voice or settings.voice_tts_default_voice,
        voice_playback_rate=runtime_settings.voice_playback_rate,
        voice_live_playback_prebuffer_segments=runtime_settings.voice_live_playback_prebuffer_segments,
        voice_live_playback_prebuffer_ms=runtime_settings.voice_live_playback_prebuffer_ms,
        chat_history_limit=settings.chat_history_limit,
        episodes_enabled=settings.episodes_enabled,
        episode_soft_inactivity_minutes=settings.episode_soft_inactivity_minutes,
        episode_hard_inactivity_minutes=settings.episode_hard_inactivity_minutes,
        episode_maximum_messages=settings.episode_maximum_messages,
        episode_maximum_estimated_tokens=settings.episode_maximum_estimated_tokens,
        memory_enabled=settings.memory_enabled,
        memory_mode=runtime_settings.memory_mode,
        memory_incognito=runtime_settings.memory_incognito,
        log_level=settings.log_level,
        api_key_configured=bool(settings.llm_api_key),
        available_personalities=AVAILABLE_PERSONALITIES,
        available_voice_languages=AVAILABLE_VOICE_LANGUAGES,
        available_tts_voices=_available_tts_voices(request),
    )


@router.patch("/settings/runtime", response_model=PublicSettingsResponse)
def patch_runtime_settings(
    payload: RuntimeSettingsPatch,
    request: Request,
) -> PublicSettingsResponse:
    runtime_settings = request.app.state.runtime_settings
    settings = request.app.state.settings
    event_bus = request.app.state.event_bus

    if payload.personality is not None:
        if payload.personality not in AVAILABLE_PERSONALITIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported personality",
            )
        runtime_settings.personality = payload.personality

    if payload.voice_language is not None:
        if payload.voice_language not in AVAILABLE_VOICE_LANGUAGES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported voice language",
            )
        runtime_settings.voice_language = payload.voice_language

    if payload.voice_tts_voice is not None:
        if payload.voice_tts_voice not in _available_tts_voices(request):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported TTS voice",
            )
        runtime_settings.voice_tts_voice = payload.voice_tts_voice

    if payload.voice_playback_rate is not None:
        if not MIN_PLAYBACK_RATE <= payload.voice_playback_rate <= MAX_PLAYBACK_RATE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported voice playback rate",
            )
        runtime_settings.voice_playback_rate = round(payload.voice_playback_rate, 2)

    if payload.voice_live_playback_prebuffer_segments is not None:
        value = payload.voice_live_playback_prebuffer_segments
        if not MIN_PREBUFFER_SEGMENTS <= value <= MAX_PREBUFFER_SEGMENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported live playback prebuffer segments",
            )
        runtime_settings.voice_live_playback_prebuffer_segments = value

    if payload.voice_live_playback_prebuffer_ms is not None:
        value = payload.voice_live_playback_prebuffer_ms
        if not MIN_PREBUFFER_MS <= value <= MAX_PREBUFFER_MS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported live playback prebuffer ms",
            )
        runtime_settings.voice_live_playback_prebuffer_ms = value

    if payload.memory_mode is not None:
        if payload.memory_mode not in MEMORY_MODES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported memory mode")
        runtime_settings.memory_mode = "balanced" if payload.memory_mode == "ask" else payload.memory_mode

    if payload.memory_incognito is not None:
        runtime_settings.memory_incognito = payload.memory_incognito

    try:
        request.app.state.runtime_settings_store.save(runtime_settings)
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not persist settings",
        ) from error

    event_bus.publish(
        "backend.status",
        "info",
        "Runtime settings updated",
        {
            "model": settings.deepseek_model,
            "personality": runtime_settings.personality,
            "voice_language": runtime_settings.voice_language,
            "voice_tts_voice": runtime_settings.voice_tts_voice,
            "voice_playback_rate": runtime_settings.voice_playback_rate,
            "voice_live_playback_prebuffer_segments": runtime_settings.voice_live_playback_prebuffer_segments,
            "voice_live_playback_prebuffer_ms": runtime_settings.voice_live_playback_prebuffer_ms,
            "memory_mode": runtime_settings.memory_mode,
            "memory_incognito": runtime_settings.memory_incognito,
        },
    )

    return get_public_settings(request)
