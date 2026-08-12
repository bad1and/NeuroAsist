from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.schemas.coding import (
    CodingInstructionCreate,
    CodingStatusResponse,
    CodingTaskClearResponse,
    CodingTaskCreate,
    CodingTaskResponse,
)

router = APIRouter(prefix="/coding", tags=["coding"])


def _service(request: Request):
    service = getattr(request.app.state, "coding_agent_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Coding Agent is unavailable")
    return service


def _task_or_404(request: Request, task_id: str) -> dict[str, object]:
    store = request.app.state.timeline_store
    task = store.get_coding_task(task_id) if store is not None else None
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding task not found")
    return task


@router.get("/status", response_model=CodingStatusResponse)
async def get_status(request: Request, refresh: bool = False) -> CodingStatusResponse:
    return CodingStatusResponse(**await _service(request).status(refresh=refresh))


@router.get("/tasks", response_model=list[CodingTaskResponse])
def list_tasks(request: Request, limit: int = 100) -> list[CodingTaskResponse]:
    store = request.app.state.timeline_store
    if store is None:
        return []
    return [CodingTaskResponse(**task) for task in store.list_coding_tasks(limit=limit)]


@router.delete("/tasks", response_model=CodingTaskClearResponse)
def clear_tasks(request: Request) -> CodingTaskClearResponse:
    try:
        removed = _service(request).clear_completed_tasks()
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return CodingTaskClearResponse(removed_tasks=removed)


@router.post("/tasks", response_model=CodingTaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(payload: CodingTaskCreate, request: Request) -> CodingTaskResponse:
    try:
        task = _service(request).create_task(
            payload.objective,
            context_files=payload.context_files,
            project_root=payload.project_root,
        )
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return CodingTaskResponse(**task)


@router.get("/tasks/{task_id}", response_model=CodingTaskResponse)
def get_task(task_id: str, request: Request) -> CodingTaskResponse:
    return CodingTaskResponse(**_task_or_404(request, task_id))


@router.post("/tasks/{task_id}/instructions", response_model=CodingTaskResponse)
def add_instruction(task_id: str, payload: CodingInstructionCreate, request: Request) -> CodingTaskResponse:
    _task_or_404(request, task_id)
    task = _service(request).add_instruction(task_id, payload.text)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding task not found")
    return CodingTaskResponse(**task)


@router.post("/tasks/{task_id}/cancel", response_model=CodingTaskResponse)
async def cancel_task(task_id: str, request: Request) -> CodingTaskResponse:
    _task_or_404(request, task_id)
    task = await _service(request).cancel(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding task not found")
    return CodingTaskResponse(**task)


@router.post("/tasks/{task_id}/retry", response_model=CodingTaskResponse)
def retry_task(task_id: str, request: Request) -> CodingTaskResponse:
    _task_or_404(request, task_id)
    task = _service(request).retry(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding task not found")
    return CodingTaskResponse(**task)


@router.post("/tasks/{task_id}/apply", response_model=CodingTaskResponse)
def apply_task(task_id: str, request: Request) -> CodingTaskResponse:
    try:
        task = _service(request).apply(task_id)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding task not found") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except RuntimeError as error:
        # The original source changed after snapshot creation.  The patch is
        # still available for review; it must not overwrite newer user edits.
        store = request.app.state.timeline_store
        if store is not None:
            store.update_coding_task(task_id, status="conflicted", error=str(error))
            store.append_coding_event(task_id, "task.conflicted", "warning", "Apply blocked by source conflict")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return CodingTaskResponse(**task)
