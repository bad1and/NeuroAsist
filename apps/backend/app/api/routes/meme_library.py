from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.backend.app.agents.character.memes import MAX_CARDS

router = APIRouter(prefix="/meme-library", tags=["developer"])


class MemeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=400)
    tags: str = Field(default="", max_length=250)
    source: str = Field(min_length=1, max_length=1000)


class MemePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    summary: str | None = Field(default=None, min_length=1, max_length=400)
    tags: str | None = Field(default=None, max_length=250)
    source: str | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool | None = None


def _library(request):
    if not getattr(getattr(request.app.state, "runtime_settings", None), "developer_mode_enabled", False):
        raise HTTPException(403, "Раздел доступен в режиме разработчика")
    library = getattr(request.app.state, "meme_library", None)
    if library is None:
        raise HTTPException(503, "Мемотека недоступна")
    return library


@router.get("")
def list_memes(request: Request):
    return {"items": _library(request).list_cards(), "limit": MAX_CARDS}


@router.post("")
def add_meme(payload: MemeCreate, request: Request):
    try:
        return {"item": _library(request).add_card(payload.model_dump())}
    except ValueError as exc:
        detail = "Мемотека заполнена. Удалите ненужную карточку." if str(exc) == "Meme library is full" else "Проверьте значение карточки и публичную ссылку на источник."
        raise HTTPException(422, detail) from exc


@router.patch("/{card_id}")
def edit_meme(card_id: str, payload: MemePatch, request: Request):
    try:
        return {"item": _library(request).edit_card(card_id, payload.model_dump(exclude_none=True))}
    except KeyError as exc:
        raise HTTPException(404, "Карточка не найдена") from exc
    except ValueError as exc:
        raise HTTPException(422, "Проверьте значение карточки и публичную ссылку на источник.") from exc


@router.delete("/{card_id}")
def delete_meme(card_id: str, request: Request):
    try:
        _library(request).delete_card(card_id)
        return {"deleted": True}
    except KeyError as exc:
        raise HTTPException(404, "Карточка не найдена") from exc
