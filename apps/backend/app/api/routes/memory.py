from fastapi import APIRouter, HTTPException, Query, Request

from apps.backend.app.schemas.memory import (
    CommitmentCreate, CommitmentPatch, MemoryClear, MemoryCreate, MemoryMerge, MemoryPatch,
    TopicCreate, TopicPatch,
)


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


@router.get("/profile")
def memory_profile(request: Request) -> dict[str, object]:
    return _service(request).store.derive_profile()


@router.post("/merge")
def merge_memory(payload: MemoryMerge, request: Request) -> dict[str, object]:
    service = _service(request)
    survivor, merged = service.store.get_memory(payload.survivor_id), service.store.get_memory(payload.merged_id)
    if survivor is None or merged is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if survivor.get("user_locked") is False and merged.get("user_locked") is True:
        raise HTTPException(status_code=422, detail="A locked memory must be the merge survivor")
    service.store.supersede_memory(payload.merged_id, payload.survivor_id)
    return {"memory": service.store.get_memory(payload.survivor_id)}


@router.get("/topics")
def list_topics(request: Request, status: str | None = None, q: str | None = Query(default=None, max_length=200)) -> dict[str, object]:
    return {"items": _service(request).store.list_topics(status=status, query=q)}


@router.post("/topics")
def create_topic(payload: TopicCreate, request: Request) -> dict[str, object]:
    return {"topic": _service(request).store.create_topic(payload.model_dump(), actor="user")}


@router.patch("/topics/{topic_id}")
def patch_topic(topic_id: str, payload: TopicPatch, request: Request) -> dict[str, object]:
    try:
        return {"topic": _service(request).store.update_topic(topic_id, payload.model_dump(exclude_none=True))}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Topic not found") from exc


@router.post("/topics/{topic_id}/merge/{merged_id}")
def merge_topics(topic_id: str, merged_id: str, request: Request) -> dict[str, object]:
    try:
        return {"topic": _service(request).store.merge_topics(topic_id, merged_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Topic not found") from exc


@router.get("/commitments")
def list_commitments(request: Request, status: str | None = None) -> dict[str, object]:
    return {"items": _service(request).store.list_commitments(status=status)}


@router.post("/commitments")
def create_commitment(payload: CommitmentCreate, request: Request) -> dict[str, object]:
    return {"commitment": _service(request).store.create_commitment(payload.model_dump())}


@router.patch("/commitments/{commitment_id}")
def patch_commitment(commitment_id: str, payload: CommitmentPatch, request: Request) -> dict[str, object]:
    try:
        return {"commitment": _service(request).store.update_commitment(commitment_id, payload.model_dump(exclude_none=True))}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Commitment not found") from exc


@router.post("/commitments/{commitment_id}/close")
def close_commitment(commitment_id: str, request: Request) -> dict[str, object]:
    try:
        return {"commitment": _service(request).store.update_commitment(commitment_id, {"status": "completed"})}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Commitment not found") from exc


@router.get("/conflicts")
def list_conflicts(request: Request, status: str | None = None) -> dict[str, object]:
    return {"items": _service(request).store.list_conflicts(status=status)}


@router.get("/diagnostics")
def memory_diagnostics(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, object]:
    return _service(request).store.memory_diagnostics(limit=limit)


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


@router.get("/index/status")
def index_status(request: Request) -> dict[str, object]:
    service = _service(request)
    return {"semantic_enabled": service.semantic_enabled, "semantic_degraded_reason": getattr(service, "_semantic_degraded_reason", None), "stale_vector_count": 0}


@router.post("/clear")
def clear_memory(payload: MemoryClear, request: Request) -> dict[str, int]:
    return {"deleted": _service(request).clear(payload.status)}


@router.post("/reset-all")
def reset_all_memory_and_timeline(request: Request) -> dict[str, int]:
    result = _service(request).reset_all()
    request.app.state.event_bus.publish("companion.data_reset", "warning", "Timeline and memory were reset", result)
    return result
