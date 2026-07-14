from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/debug/context", tags=["debug"])


@router.get("/preview")
def preview_context(request: Request, message: str = Query(min_length=1, max_length=8000)) -> dict[str, object]:
    manager = request.app.state.context_manager
    if manager is None:
        raise HTTPException(status_code=503, detail="Context Manager is disabled")
    context = manager.build(message)
    return {"messages": [{"role": item.role, "content": item.content} for item in context.messages], "token_estimate": context.token_estimate, "diagnostics": context.diagnostics}


@router.get("/last")
def last_context(request: Request) -> dict[str, object]:
    manager = request.app.state.context_manager
    if manager is None or manager.last is None:
        raise HTTPException(status_code=404, detail="No context has been built")
    context = manager.last
    return {"token_estimate": context.token_estimate, "diagnostics": context.diagnostics}
