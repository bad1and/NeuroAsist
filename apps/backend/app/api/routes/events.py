from fastapi import APIRouter, Query, Request

from apps.backend.app.schemas.events import EventsResponse

router = APIRouter()


@router.get("/events", response_model=EventsResponse)
def get_events(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> EventsResponse:
    event_bus = request.app.state.event_bus
    return EventsResponse(
        events=[
            event.model_dump()
            for event in event_bus.get_recent_events(limit)
        ]
    )
