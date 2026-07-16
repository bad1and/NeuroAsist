from fastapi import APIRouter, HTTPException, Query, Request

from apps.backend.app.schemas.memory import MemoryClear, MemoryCreate, MemoryPatch


router = APIRouter(prefix="/memory", tags=["memory"])


def _service(request: Request):
    service = getattr(request.app.state, "memory_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Long-term memory is disabled")
    return service


@router.get("")
def list_memory(
    request: Request,
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    return {"items": _service(request).store.list_memories(status=status, query=q, limit=limit)}


@router.post("")
def create_memory(payload: MemoryCreate, request: Request) -> dict[str, object]:
    try:
        memory = _service(request).create_manual(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"memory": memory}


@router.patch("/{memory_id}")
def patch_memory(memory_id: str, payload: MemoryPatch, request: Request) -> dict[str, object]:
    try:
        memory = _service(request).edit(memory_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory not found") from exc
    return {"memory": memory}


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, request: Request) -> dict[str, object]:
    try:
        return {"memory": _service(request).delete(memory_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory not found") from exc


@router.post("/{memory_id}/restore")
def restore_memory(memory_id: str, request: Request) -> dict[str, object]:
    try:
        return {"memory": _service(request).restore(memory_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory not found") from exc


@router.post("/{memory_id}/confirm")
def confirm_memory(memory_id: str, request: Request) -> dict[str, object]:
    try:
        return {"memory": _service(request).confirm(memory_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory not found") from exc


@router.post("/{memory_id}/reject")
def reject_memory(memory_id: str, request: Request) -> dict[str, object]:
    try:
        return {"memory": _service(request).reject(memory_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory not found") from exc


@router.get("/retrieval/explain")
def explain_retrieval(request: Request, q: str = Query(min_length=1, max_length=200), limit: int = Query(default=8, ge=1, le=50)) -> dict[str, object]:
    return _service(request).explain_retrieval(q, limit)


@router.get("/{memory_id}/audit")
def memory_audit(memory_id: str, request: Request) -> dict[str, object]:
    service = _service(request)
    if service.store.get_memory(memory_id) is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"items": service.store.memory_audit(memory_id)}


@router.post("/reindex")
def reindex_memory(request: Request) -> dict[str, object]:
    return _service(request).reindex()


@router.post("/clear")
def clear_memory(payload: MemoryClear, request: Request) -> dict[str, int]:
    return {"deleted": _service(request).clear(payload.status)}


@router.post("/reset-all")
def reset_all_memory_and_timeline(request: Request) -> dict[str, int]:
    result = _service(request).reset_all()
    request.app.state.event_bus.publish("companion.data_reset", "warning", "Timeline and memory were reset", result)
    return result
