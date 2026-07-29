from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.schemas.settings import (
    PublicSettingsResponse,
    PronunciationsPatch,
    SttTermsPatch,
    RuntimeSettingsPatch,
    VoiceExpressionPatch,
    VoiceStylePatch,
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
LIVE_SETTING_VALUES = {
    "live_conversation_participant_mode": {"one_to_one", "group"},
    "live_conversation_engagement": {"low", "balanced", "high"},
    "live_conversation_initiative": {"off", "rare", "balanced"},
    "live_conversation_address_strictness": {"relaxed", "balanced", "strict"},
    "live_conversation_interruption_sensitivity": {"low", "balanced", "high"},
    "live_conversation_pause_tolerance": {"short", "natural", "patient"},
    "live_conversation_emotion_expression": {"subtle", "natural", "strong"},
    "live_conversation_mood_recovery": {"slow", "natural", "fast"},
    "live_conversation_recent_event_weight": {"light", "balanced", "strong"},
    "live_conversation_echo_mode": {"auto", "half_duplex"},
}


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
        voice_microphone_profile=runtime_settings.voice_microphone_profile,
        voice_vad=dict(request.app.state.voice_input_session_manager.vad_status),
        voice_input_diagnostic_audio_enabled=settings.voice_input_diagnostic_audio,
        voice_stt_model=settings.voice_stt_model,
        voice_tts_enabled=settings.voice_tts_enabled,
        voice_tts_provider=str(tts_metadata.get("provider", tts_provider.name)),
        voice_tts_model=tts_metadata.get("model"),
        voice_tts_device=tts_metadata.get("device"),
        avatar_enabled=settings.avatar_enabled,
        voice_tts_voice=runtime_settings.voice_tts_voice or settings.voice_tts_default_voice,
        voice_tts_style=str(getattr(request.app.state, "voice_tts_style", "auto")),
        voice_tts_expression_level=str(getattr(request.app.state, "voice_tts_expression_level", "natural")),
        voice_playback_rate=runtime_settings.voice_playback_rate,
        voice_live_playback_prebuffer_segments=runtime_settings.voice_live_playback_prebuffer_segments,
        voice_live_playback_prebuffer_ms=runtime_settings.voice_live_playback_prebuffer_ms,
        voice_live_playback_start_lead_ms=settings.voice_live_playback_start_lead_ms,
        chat_history_limit=settings.chat_history_limit,
        episodes_enabled=settings.episodes_enabled,
        episode_soft_inactivity_minutes=settings.episode_soft_inactivity_minutes,
        episode_hard_inactivity_minutes=settings.episode_hard_inactivity_minutes,
        episode_maximum_messages=settings.episode_maximum_messages,
        episode_maximum_estimated_tokens=settings.episode_maximum_estimated_tokens,
        memory_enabled=settings.memory_enabled,
        memory_mode=runtime_settings.memory_mode,
        memory_incognito=runtime_settings.memory_incognito,
        reflections_enabled=runtime_settings.reflections_enabled,
        reflection_min_significance=runtime_settings.reflection_min_significance,
        conversation_diagnostics_enabled=settings.conversation_diagnostics_enabled,
        live_conversation_enabled=runtime_settings.live_conversation_enabled,
        live_conversation_participant_mode=runtime_settings.live_conversation_participant_mode,
        live_conversation_engagement=runtime_settings.live_conversation_engagement,
        live_conversation_initiative=runtime_settings.live_conversation_initiative,
        live_conversation_address_strictness=runtime_settings.live_conversation_address_strictness,
        live_conversation_interruption_sensitivity=runtime_settings.live_conversation_interruption_sensitivity,
        live_conversation_pause_tolerance=runtime_settings.live_conversation_pause_tolerance,
        live_conversation_emotion_expression=runtime_settings.live_conversation_emotion_expression,
        live_conversation_mood_recovery=runtime_settings.live_conversation_mood_recovery,
        live_conversation_recent_event_weight=runtime_settings.live_conversation_recent_event_weight,
        live_conversation_echo_mode=runtime_settings.live_conversation_echo_mode,
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

    if payload.voice_microphone_profile is not None:
        if payload.voice_microphone_profile not in {"headset", "balanced", "speakers"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported microphone profile",
            )
        runtime_settings.voice_microphone_profile = payload.voice_microphone_profile

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

    if payload.reflections_enabled is not None:
        runtime_settings.reflections_enabled = payload.reflections_enabled
    if payload.reflection_min_significance is not None:
        if not 0.3 <= payload.reflection_min_significance <= 1.0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported reflection significance")
        runtime_settings.reflection_min_significance = round(payload.reflection_min_significance, 2)

    if payload.live_conversation_enabled is not None:
        runtime_settings.live_conversation_enabled = payload.live_conversation_enabled

    for field_name, allowed_values in LIVE_SETTING_VALUES.items():
        value = getattr(payload, field_name)
        if value is None:
            continue
        if value not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported {field_name.replace('_', ' ')}",
            )
        setattr(runtime_settings, field_name, value)

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
            "voice_microphone_profile": runtime_settings.voice_microphone_profile,
            "voice_tts_voice": runtime_settings.voice_tts_voice,
            "voice_playback_rate": runtime_settings.voice_playback_rate,
            "voice_live_playback_prebuffer_segments": runtime_settings.voice_live_playback_prebuffer_segments,
            "voice_live_playback_prebuffer_ms": runtime_settings.voice_live_playback_prebuffer_ms,
            "memory_mode": runtime_settings.memory_mode,
            "memory_incognito": runtime_settings.memory_incognito,
            "reflections_enabled": runtime_settings.reflections_enabled,
            "reflection_min_significance": runtime_settings.reflection_min_significance,
            "live_conversation_enabled": runtime_settings.live_conversation_enabled,
            **{
                field_name: getattr(runtime_settings, field_name)
                for field_name in LIVE_SETTING_VALUES
            },
        },
    )

    return get_public_settings(request)


@router.patch("/settings/voice-style", response_model=PublicSettingsResponse)
def patch_voice_style(payload: VoiceStylePatch, request: Request) -> PublicSettingsResponse:
    from apps.backend.app.voice.style import VoiceStyle

    try:
        style = VoiceStyle(payload.voice_tts_style)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported voice style") from error
    request.app.state.voice_tts_style = style.value
    request.app.state.event_bus.publish(
        "voice.style_changed", "info", "Temporary voice style changed", {"style": style.value}
    )
    return get_public_settings(request)


@router.patch("/settings/voice-expression", response_model=PublicSettingsResponse)
def patch_voice_expression(payload: VoiceExpressionPatch, request: Request) -> PublicSettingsResponse:
    from apps.backend.app.voice.style import VoiceExpressionLevel

    try:
        level = VoiceExpressionLevel(payload.voice_tts_expression_level)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported voice expression level") from error
    request.app.state.voice_tts_expression_level = level.value
    request.app.state.voice_service.set_tts_expression_level(level.value)
    request.app.state.event_bus.publish(
        "voice.expression_changed", "info", "Temporary voice expression level changed", {"level": level.value}
    )
    return get_public_settings(request)


@router.get("/settings/pronunciations")
def get_pronunciations(request: Request) -> dict[str, dict[str, str]]:
    return {"pronunciations": request.app.state.voice_service.pronunciations()}


@router.put("/settings/pronunciations")
def put_pronunciations(payload: PronunciationsPatch, request: Request) -> dict[str, dict[str, str]]:
    return {"pronunciations": request.app.state.voice_service.update_pronunciations(payload.pronunciations)}


@router.get("/settings/stt-terms")
def get_stt_terms(request: Request) -> dict[str, dict[str, list[str]]]:
    return {"terms": request.app.state.voice_service.stt_terms()}


@router.put("/settings/stt-terms")
def put_stt_terms(
    payload: SttTermsPatch,
    request: Request,
) -> dict[str, dict[str, list[str]]]:
    try:
        terms = request.app.state.voice_service.update_stt_terms(payload.terms)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {"terms": terms}
