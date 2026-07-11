from fastapi import APIRouter, Request

from apps.backend.app.schemas.status import StatusResponse

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
def get_status(request: Request) -> StatusResponse:
    settings = request.app.state.settings
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
        llm_model=settings.deepseek_model,
        api_key_configured=bool(settings.llm_api_key),
        database=database_status,
    )
