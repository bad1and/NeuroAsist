from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter(tags=["maintenance"])


class BackupItem(BaseModel):
    name: str
    size_bytes: int
    created_at: str


@router.get("/diagnostics")
def diagnostics(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "app_data_directory": str(settings.app_data_path),
        "database_path": str(settings.database_path),
        "models": request.app.state.model_manager.states(),
        "log_level": settings.log_level,
        "api_key_configured": bool(settings.llm_api_key),
    }


@router.get("/backups", response_model=list[BackupItem])
def list_backups(request: Request) -> list[BackupItem]:
    return [BackupItem(**item) for item in request.app.state.backup_service.list()]


@router.post("/backups", response_model=BackupItem, status_code=status.HTTP_201_CREATED)
def create_backup(request: Request) -> BackupItem:
    return BackupItem(**request.app.state.backup_service.create())


@router.delete("/backups/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(name: str, request: Request) -> None:
    try:
        request.app.state.backup_service.delete(name)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid backup name") from error
