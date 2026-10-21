from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from apps.backend.app.reminders import ReminderArguments

router = APIRouter(prefix="/reminders", tags=["reminders"])

def service(request: Request):
    result = getattr(request.app.state, "reminder_service", None)
    if result is None:
        raise HTTPException(503, "Напоминания недоступны в текущем режиме хранения")
    return result

class ReminderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "completed", "cancelled"] | None = None
    due_at: str | None = Field(default=None, max_length=50)

class Acknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivery_token: str = Field(min_length=1, max_length=100)

@router.get("")
def list_reminders(request: Request, due_only: bool = False):
    return {"items": service(request).list(due_only=due_only)}

@router.post("")
def create_reminder(payload: ReminderArguments, request: Request):
    try:
        return service(request).create(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@router.patch("/{identifier}")
def update_reminder(identifier: str, payload: ReminderPatch, request: Request):
    try:
        return service(request).update(identifier, **payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(404, "Напоминание не найдено") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@router.post("/{identifier}/ack")
def acknowledge_reminder(identifier: str, payload: Acknowledgement, request: Request):
    return {"acknowledged": service(request).acknowledge(identifier, payload.delivery_token)}
