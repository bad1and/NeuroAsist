from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.schemas.settings import (
    PublicSettingsResponse,
    RuntimeSettingsPatch,
)

router = APIRouter()
AVAILABLE_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]
AVAILABLE_PERSONALITIES = ["default"]
AVAILABLE_VOICE_LANGUAGES = ["auto", "ru", "en"]


def _available_tts_voices(settings) -> list[str]:
    return [settings.voice_tts_voice_ru, settings.voice_tts_voice_en]


@router.get("/settings/public", response_model=PublicSettingsResponse)
def get_public_settings(request: Request) -> PublicSettingsResponse:
    settings = request.app.state.settings
    runtime_settings = request.app.state.runtime_settings

    return PublicSettingsResponse(
        provider="deepseek",
        model=runtime_settings.model,
        personality=runtime_settings.personality,
        voice_language=runtime_settings.voice_language,
        voice_stt_model=settings.voice_stt_model,
        voice_tts_enabled=settings.voice_tts_enabled,
        voice_tts_voice=runtime_settings.voice_tts_voice or settings.voice_tts_voice_ru,
        chat_history_limit=settings.chat_history_limit,
        log_level=settings.log_level,
        api_key_configured=bool(settings.llm_api_key),
        available_models=AVAILABLE_MODELS,
        available_personalities=AVAILABLE_PERSONALITIES,
        available_voice_languages=AVAILABLE_VOICE_LANGUAGES,
        available_tts_voices=_available_tts_voices(settings),
    )


@router.patch("/settings/runtime", response_model=PublicSettingsResponse)
def patch_runtime_settings(
    payload: RuntimeSettingsPatch,
    request: Request,
) -> PublicSettingsResponse:
    runtime_settings = request.app.state.runtime_settings
    settings = request.app.state.settings
    event_bus = request.app.state.event_bus

    if payload.model is not None:
        if payload.model not in AVAILABLE_MODELS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported model",
            )
        runtime_settings.model = payload.model

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
        if payload.voice_tts_voice not in _available_tts_voices(settings):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported TTS voice",
            )
        runtime_settings.voice_tts_voice = payload.voice_tts_voice

    event_bus.publish(
        "backend.status",
        "info",
        "Runtime settings updated",
        {
            "model": runtime_settings.model,
            "personality": runtime_settings.personality,
            "voice_language": runtime_settings.voice_language,
            "voice_tts_voice": runtime_settings.voice_tts_voice,
        },
    )

    return get_public_settings(request)
