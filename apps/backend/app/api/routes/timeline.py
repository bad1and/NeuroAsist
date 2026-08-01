from fastapi import APIRouter, HTTPException, Query, Request

from apps.backend.app.schemas.timeline import TimelineCorrection, TimelineMessageCreate


router = APIRouter(prefix="/timeline", tags=["timeline"])


def _store(request: Request):
    store = request.app.state.timeline_store
    if store is None:
        raise HTTPException(status_code=503, detail="Timeline V2 is disabled")
    return store


@router.get("")
def get_timeline(request: Request) -> dict[str, object]:
    return _store(request).timeline()


@router.get("/messages")
def get_messages(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session_id: str | None = Query(default=None, min_length=1, max_length=128),
) -> dict[str, object]:
    messages, next_offset = _store(request).list_messages(limit, offset, session_id)
    return {"items": [message.as_dict() for message in messages], "next_offset": next_offset}


@router.post("/messages")
def post_message(payload: TimelineMessageCreate, request: Request) -> dict[str, object]:
    message, created = _store(request).append_message(**payload.model_dump())
    request.app.state.event_bus.publish(
        "timeline.message_appended" if created else "timeline.message_deduplicated",
        "info",
        "Timeline message stored" if created else "Timeline message deduplicated",
        {"timeline_id": message.timeline_id, "message_id": message.id, "role": message.role, "input_mode": message.input_mode},
    )
    return {"message": message.as_dict(), "created": created}


@router.patch("/messages/{message_id}")
def correct_message(message_id: str, payload: TimelineCorrection, request: Request) -> dict[str, object]:
    try:
        message = _store(request).correct_message(message_id, payload.corrected_content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Timeline message not found") from exc
    request.app.state.event_bus.publish(
        "timeline.message_corrected",
        "info",
        "Timeline message correction stored",
        {"timeline_id": message.timeline_id, "message_id": message.id},
    )
    return {"message": message.as_dict()}


@router.post("/stop")
def stop_message(message_id: str, request: Request) -> dict[str, object]:
    try:
        message = _store(request).cancel_message(message_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Timeline message not found") from exc
    return {"message": message.as_dict()}


@router.get("/journal")
def get_journal(request: Request) -> dict[str, object]:
    return {"items": _store(request).journal()}


@router.get("/search")
def search_timeline(request: Request, q: str = Query(min_length=1, max_length=200), limit: int = Query(default=20, ge=1, le=100)) -> dict[str, object]:
    return {"items": [message.as_dict() for message in _store(request).search_messages(q, limit)]}


@router.delete("/range")
def delete_range(request: Request, before: str | None = None, after: str | None = None) -> dict[str, int]:
    try:
        deleted = _store(request).delete_range(before, after)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    request.app.state.event_bus.publish(
        "timeline.range_deleted",
        "warning",
        "Timeline range deleted",
        {"deleted": deleted},
    )
    return {"deleted": deleted}
