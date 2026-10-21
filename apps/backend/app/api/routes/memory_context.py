from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/memory-context", tags=["developer"])

def developer(request: Request):
    if not request.app.state.runtime_settings.developer_mode_enabled:
        raise HTTPException(403, "Сведения о контексте доступны в режиме разработчика")
    return request.app.state.timeline_store

@router.get("/{message_id}")
def used_memories(message_id: str, request: Request):
    store = developer(request)
    message = store.get_message(message_id) if store else None
    if message is None or message.role != "assistant":
        raise HTTPException(404, "Ответ не найден")
    records = message.metadata.get("context_memories", [])
    return {"items": [{**item, "current": store.get_memory(str(item["id"]))} for item in records if isinstance(item, dict) and item.get("id")],
        "description": "Сохранённые фрагменты входного контекста этого ответа. Они не доказывают, что каждый факт повлиял на формулировку."}

class Exclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    memory_id: str = Field(min_length=1, max_length=128)

@router.post("/exclude-next")
async def exclude_memory(payload: Exclusion, request: Request):
    from apps.backend.app.api.routes.conversation import require_active_session_async
    store = developer(request)
    await require_active_session_async(request, payload.session_id)
    if store is None or store.get_memory(payload.memory_id) is None:
        raise HTTPException(404, "Запись памяти не найдена")
    request.app.state.context_manager.exclude_memory_once(payload.session_id, payload.memory_id)
    return {"excluded_for_next_turn": True}
