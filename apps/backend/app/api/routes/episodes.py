from fastapi import APIRouter, HTTPException, Query, Request


router = APIRouter(prefix="/episodes", tags=["episodes"])


def _store(request: Request):
    store = request.app.state.timeline_store
    if store is None or not request.app.state.settings.episodes_enabled:
        raise HTTPException(status_code=503, detail="Episodes are disabled")
    return store


@router.get("")
def get_episodes(request: Request, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    return {"items": _store(request).list_episodes(limit)}


@router.get("/{episode_id}")
def get_episode(episode_id: str, request: Request) -> dict[str, object]:
    episode = _store(request).get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    return {"episode": episode}


@router.post("/current/close")
def close_current_episode(request: Request) -> dict[str, object]:
    episode = _store(request).close_current_episode()
    if episode is None:
        raise HTTPException(status_code=409, detail="No active episode")
    request.app.state.event_bus.publish(
        "episode.manual_close_requested", "info", "Current episode closed manually", {"episode_id": episode["id"]}
    )
    return {"episode": episode}


@router.delete("/{episode_id}")
def delete_episode(episode_id: str, request: Request) -> dict[str, int]:
    try:
        deleted = _store(request).delete_episode(episode_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Episode not found") from exc
    request.app.state.event_bus.publish(
        "episode.deleted", "warning", "Episode and its messages deleted", {"episode_id": episode_id, "deleted_messages": deleted}
    )
    return {"deleted_messages": deleted}
