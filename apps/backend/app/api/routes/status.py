from fastapi import APIRouter, Request

from apps.backend.app.schemas.status import StatusResponse

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
def get_status(request: Request) -> StatusResponse:
    settings = request.app.state.settings
    runtime_settings = request.app.state.runtime_settings
    history = request.app.state.history

    try:
        history.check_health()
        database_status = "ok"
    except Exception:
        database_status = "error"

    return StatusResponse(
        app_name=settings.app_name,
        version=request.app.version,
        backend="ok",
        llm_provider="deepseek",
        llm_model=runtime_settings.model,
        api_key_configured=bool(settings.llm_api_key),
        database=database_status,
    )
