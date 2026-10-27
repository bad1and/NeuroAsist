"""Developer-only inspection of Iris viewpoints; never user-profile memory."""
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.backend.app.agents.character.opinions import MAX_OPINIONS, OpinionProposal, OpinionConflict

router = APIRouter(prefix="/opinions", tags=["developer"])


def _store(request):
    if not getattr(getattr(request.app.state, "runtime_settings", None), "developer_mode_enabled", False):
        raise HTTPException(403, "Раздел доступен в режиме разработчика")
    store = getattr(request.app.state, "opinion_store", None)
    if store is None:
        raise HTTPException(503, "Взгляды Iris недоступны")
    return store


class OpinionToggle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    revision: int = Field(ge=1)


@router.get("")
def list_opinions(request: Request):
    return {"items": _store(request).list_items(), "limit": MAX_OPINIONS}


@router.get("/{opinion_id}/history")
def opinion_history(opinion_id: str, request: Request):
    try:
        return {"items": _store(request).history(opinion_id)}
    except KeyError as exc:
        raise HTTPException(404, "Позиция не найдена") from exc


@router.post("")
def save_opinion(payload: OpinionProposal, request: Request):
    try:
        return _store(request).apply(payload, origin="developer")
    except OpinionConflict as exc:
        raise HTTPException(409, "Позиция уже существует или была изменена. Обновите список и проверьте историю.") from exc
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "Не удалось сохранить позицию") from exc


@router.patch("/{opinion_id}")
def toggle_opinion(opinion_id: str, payload: OpinionToggle, request: Request):
    try:
        _store(request).set_enabled(opinion_id, payload.enabled, payload.revision)
        return {"updated": True}
    except KeyError as exc:
        raise HTTPException(404, "Позиция не найдена") from exc
    except OpinionConflict as exc:
        raise HTTPException(409, "Позиция уже изменена. Обновите список.") from exc
