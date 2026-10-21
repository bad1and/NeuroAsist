from fastapi import APIRouter, HTTPException, Query, Request

from apps.backend.app.schemas.timeline import TimelineCorrection, TimelineMessageCreate


router = APIRouter(prefix="/timeline", tags=["timeline"])


def _message_view(message, request: Request):
    result = message.as_dict()
    if not getattr(getattr(request.app.state, "runtime_settings", None), "developer_mode_enabled", False):
        result["metadata"] = {key: value for key, value in result.get("metadata", {}).items() if key != "context_memories"}
    return result


@router.get("/messages/{message_id}/context")
def message_context(message_id: str, request: Request):
    store = _store(request)
    message = store.get_message(message_id)
    if message is None:
        raise HTTPException(404, "Сообщение не найдено")
    scope_column = "episode_id" if message.episode_id else "session_id"
    scope_value = message.episode_id or message.session_id
    with store._connect() as connection:
        counts = connection.execute(f"""SELECT COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN sequence_no > ? THEN 1 ELSE 0 END), 0) AS newer
            FROM conversation_messages WHERE timeline_id = ? AND {scope_column} IS ?""",
            (message.sequence_no, message.timeline_id, scope_value)).fetchone()
    offset = max(0, int(counts["newer"]) - 30)
    messages, next_offset = store.list_messages(80, offset, episode_id=message.episode_id, session_id=None if message.episode_id else message.session_id)
    episode = store.get_episode(message.episode_id) if message.episode_id else None
    episode = episode or {}
    return {"items": [_message_view(item, request) for item in messages], "next_offset": next_offset, "offset": offset,
        "episode": {"id": message.episode_id, "session_id": message.session_id, "day": message.created_at[:10], "title": episode.get("title") or "Найденное сообщение",
            "message_count": counts["total"], "started_at": episode.get("started_at") or message.created_at,
            "last_activity_at": episode.get("last_activity_at") or message.created_at}}


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
    episode_id: str | None = Query(default=None, min_length=1, max_length=128),
) -> dict[str, object]:
    messages, next_offset = _store(request).list_messages(
        limit, offset, session_id=session_id, episode_id=episode_id
    )
    return {"items": [_message_view(message, request) for message in messages], "next_offset": next_offset}


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
    return {"items": [_message_view(message, request) for message in _store(request).search_messages(q, limit)]}


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


@router.delete("/history")
def clear_history(request: Request) -> dict[str, int]:
    deleted = _store(request).clear_history()
    request.app.state.event_bus.publish(
        "timeline.history_deleted", "warning", "All conversation history deleted", {"deleted": deleted}
    )
    return {"deleted": deleted}
