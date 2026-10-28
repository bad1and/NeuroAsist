import asyncio
import re

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from apps.backend.app.api.routes.conversation import require_active_session_async
from apps.backend.app.documents import DocumentError, MAX_BYTES, extract_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("")
async def upload_document(request: Request, session_id: str = Form(...), upload_id: str = Form(...), file: UploadFile = File(...)):
    try:
        await require_active_session_async(request, session_id)
        if not re.fullmatch(r"[a-zA-Z0-9-]{16,64}", upload_id):
            raise HTTPException(422, "Некорректный идентификатор загрузки")
        data = bytearray()
        while chunk := await file.read(64 * 1024):
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise DocumentError("Выберите файл размером до 10 МБ.")
        name, units = await asyncio.to_thread(extract_document, file.filename or "", bytes(data), lambda: request.app.state.document_service.cancelled(session_id, upload_id))
        if await request.is_disconnected():
            request.app.state.document_service.cancel(session_id, upload_id)
            raise HTTPException(499, "Загрузка отменена")
        metadata = request.app.state.document_service.put(session_id, upload_id, name, units).metadata()
        request.app.state.event_bus.publish("documents.changed", "info", "Conversation document updated", {"session_id": session_id})
        return metadata
    except DocumentError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()


@router.get("/current")
async def current_document(request: Request, session_id: str):
    await require_active_session_async(request, session_id)
    return {"document": request.app.state.document_service.current(session_id)}


@router.delete("/{identifier}")
def delete_document(request: Request, identifier: str, session_id: str):
    request.app.state.document_service.cancel(session_id, identifier)
    request.app.state.event_bus.publish("documents.changed", "info", "Conversation document removed", {"session_id": session_id})
    return {"removed": True}


@router.get("/{identifier}/sources/{source_id}")
def document_source(request: Request, identifier: str, source_id: str, session_id: str):
    try:
        doc = request.app.state.document_service.get(session_id, identifier)
        unit = next((unit for unit in doc.units if unit.id == source_id), None)
        if unit is None:
            raise DocumentError("Фрагмент не найден")
        return {"id": unit.id, "label": unit.label, "text": unit.text}
    except DocumentError as exc:
        raise HTTPException(404, str(exc)) from exc
