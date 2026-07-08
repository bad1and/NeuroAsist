from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.schemas.settings import (
    PublicSettingsResponse,
    RuntimeSettingsPatch,
)

router = APIRouter()
AVAILABLE_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]
AVAILABLE_PERSONALITIES = ["default"]


@router.get("/settings/public", response_model=PublicSettingsResponse)
def get_public_settings(request: Request) -> PublicSettingsResponse:
    settings = request.app.state.settings
    runtime_settings = request.app.state.runtime_settings

    return PublicSettingsResponse(
        provider="deepseek",
        model=runtime_settings.model,
        personality=runtime_settings.personality,
        chat_history_limit=settings.chat_history_limit,
        log_level=settings.log_level,
        api_key_configured=bool(settings.llm_api_key),
        available_models=AVAILABLE_MODELS,
        available_personalities=AVAILABLE_PERSONALITIES,
    )


@router.patch("/settings/runtime", response_model=PublicSettingsResponse)
def patch_runtime_settings(
    payload: RuntimeSettingsPatch,
    request: Request,
) -> PublicSettingsResponse:
    runtime_settings = request.app.state.runtime_settings
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

    event_bus.publish(
        "backend.status",
        "info",
        "Runtime settings updated",
        {
            "model": runtime_settings.model,
            "personality": runtime_settings.personality,
        },
    )

    return get_public_settings(request)
