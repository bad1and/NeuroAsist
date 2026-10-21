from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter(tags=["maintenance"])


@router.get("/maintenance/preview")
def maintenance_preview(request: Request) -> dict[str, int]:
    """Counts only; no personal contents or filesystem paths leave this preview."""
    store = request.app.state.timeline_store
    if store is None:
        raise HTTPException(503, "Timeline V2 is disabled")
    from apps.backend.app.storage.timeline import PRIMARY_RELATIONSHIP_ID, PRIMARY_TIMELINE_ID
    with store._connect() as connection:
        def count(table, clause, value):
            return int(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE {clause}", (value,)).fetchone()[0])
        return {
            "messages": count("conversation_messages", "timeline_id = ?", PRIMARY_TIMELINE_ID),
            "episodes": count("conversation_episodes", "timeline_id = ?", PRIMARY_TIMELINE_ID),
            "memories": count("memory_items", "relationship_id = ? AND status NOT IN ('deleted', 'rejected', 'superseded')", PRIMARY_RELATIONSHIP_ID),
            "archived_memories": count("memory_items", "relationship_id = ? AND status IN ('deleted', 'rejected', 'superseded')", PRIMARY_RELATIONSHIP_ID),
            "plans": int(connection.execute("SELECT COUNT(*) FROM memory_commitments").fetchone()[0]),
        }


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
