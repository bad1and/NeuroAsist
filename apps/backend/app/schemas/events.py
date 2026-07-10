from typing import Any

from pydantic import BaseModel


class EventResponse(BaseModel):
    id: str
    type: str
    level: str
    message: str
    created_at: str
    metadata: dict[str, Any]


class EventsResponse(BaseModel):
    events: list[EventResponse]
