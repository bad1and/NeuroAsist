import asyncio

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.api.routes.settings import _commit_runtime_settings_patch
from apps.backend.app.schemas.character_state import CharacterStatePublicView, EmotionCausePublicView, MoodPublicView, ReflectionPublicView, ReflectionSettingsView, RelationshipProfilePublicView

router = APIRouter(prefix="/conversation", tags=["conversation"])


class StateResetRequest(BaseModel):
    scope: str = Field(pattern="^(mood|relationship)$")


def _state_view(request: Request) -> dict[str, object]:
    service = getattr(request.app.state, "character_state_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Character state unavailable")
    context = service.current()
    return {
        "affect": context.affect.as_dict(),
        "relationship": context.relationship.as_dict(),
        "profile": context.profile.__dict__,
        "behavior": {"mood": context.behavior.dominant_mood_instruction, "expression": context.behavior.expression_strength},
    }


_RUSSIAN_CAUSE_LABELS: dict[str, str] = {
    "insult": "грубость / оскорбление",
    "shared_success": "общий успех",
    "shared success": "общий успех",
    "important_news": "яркая новость",
    "important news": "яркая новость",
    "apology": "примирение",
    "broken_promise": "нарушенное обещание",
    "promise_made": "обещание",
    "vulnerability": "откровенность",
    "support": "поддержка",
    "praise": "похвала",
    "teasing": "подкол / шутка",
    "disagreement": "разногласие",
    "rejection": "дистанция",
    "user_frustration": "переживание",
}


@router.get("/state", response_model=CharacterStatePublicView)
def character_state(request: Request) -> CharacterStatePublicView:
    service = getattr(request.app.state, "character_state_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Character state unavailable")
    context = service.current()
    profile = context.profile
    return CharacterStatePublicView(
        mood=MoodPublicView(primary_emotion=context.affect.primary_emotion, expression_strength=context.behavior.expression_strength, secondary_emotions=context.affect.secondary_emotions),
        relationship=RelationshipProfilePublicView(**{key: value for key, value in profile.__dict__.items() if key in RelationshipProfilePublicView.model_fields}),
        causes=[
            EmotionCausePublicView(
                label=str(cause.get("display_label") or _RUSSIAN_CAUSE_LABELS.get(cause.get("event_kind"), cause.get("event_kind", "событие"))),
                status=str(cause.get("status", "active")),
            )
            for cause in context.affect.causes[:8]
        ],
        incognito=bool(request.app.state.runtime_settings.memory_incognito),
        updated_at=context.affect.updated_at,
    )


@router.get("/state/events")
def character_state_events(request: Request, limit: int = 50, cursor: str | None = None) -> dict[str, object]:
    store = getattr(request.app.state, "timeline_store", None)
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Timeline V2 is disabled")
    events = store.list_character_state_events("primary", limit=limit, before=cursor)
    for ev in events:
        cause_ids = ev.get("cause_message_ids") or []
        if cause_ids:
            try:
                msg = store.get_message(str(cause_ids[0]))
                if msg is not None and msg.content:
                    ev["snippet"] = msg.content[:120].strip()
            except Exception:
                pass
    return {"events": events, "next_cursor": events[-1]["created_at"] if len(events) == limit else None}


@router.get("/state/debug")
def character_state_debug(request: Request) -> dict[str, object]:
    if not request.app.state.settings.conversation_diagnostics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _state_view(request)


@router.get("/state/reflections")
def character_reflections(request: Request) -> dict[str, object]:
    store = getattr(request.app.state, "timeline_store", None)
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Timeline V2 is disabled")
    labels = {
        "acquaintance": "Значимое знакомство",
        "vulnerability": "Личное раскрытие",
        "apology": "Искреннее примирение",
        "shared_success": "Общий успех",
        "broken_promise": "Нарушенное обещание",
        "promise_fulfilled": "Выполненное обещание",
        "iris_mistake_corrected": "Исправление ошибки Iris",
        "milestone": "Важная веха",
        "episode_closed": "Завершение значимого эпизода",
    }
    reflections = []
    for item in store.list_reflections("primary"):
        trigger_kind = str(item.get("trigger_kind", "event"))
        reflections.append(ReflectionPublicView(
            id=str(item["id"]),
            text=str(item["text"]),
            trigger_kind=trigger_kind,
            trigger_label=labels.get(trigger_kind, "Значимый эпизод"),
            significance=float(item["significance"]),
            primary_emotion=str(item["primary_emotion"]),
            created_at=str(item["created_at"]),
        ).model_dump())
    return {"reflections": reflections}


@router.delete("/state/reflections/{reflection_id}")
def delete_character_reflection(reflection_id: str, request: Request) -> dict[str, bool]:
    store = getattr(request.app.state, "timeline_store", None)
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Timeline V2 is disabled")
    if not store.delete_reflection(reflection_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reflection not found")
    return {"deleted": True}


@router.post("/state/reset")
def reset_character_state(payload: StateResetRequest, request: Request) -> dict[str, object]:
    service = getattr(request.app.state, "character_state_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Character state unavailable")
    try:
        service.reset(payload.scope)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    request.app.state.event_bus.publish("character.state_reset", "warning", "Character state reset", {"scope": payload.scope})
    return _state_view(request)


@router.post("/state/mood/reset")
def reset_character_mood(request: Request) -> dict[str, object]:
    return reset_character_state(StateResetRequest(scope="mood"), request)


@router.post("/state/relationship/reset")
def reset_character_relationship(request: Request) -> dict[str, object]:
    return reset_character_state(StateResetRequest(scope="relationship"), request)


@router.patch("/state/reflections/settings", response_model=ReflectionSettingsView)
def patch_reflection_settings(payload: ReflectionSettingsView, request: Request) -> ReflectionSettingsView:
    runtime = request.app.state.runtime_settings
    try:
        _commit_runtime_settings_patch(
            request.app.state.runtime_settings_store,
            runtime,
            {
                "reflections_enabled": payload.enabled,
                "reflection_min_significance": payload.min_significance,
            },
        )
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not persist reflection settings",
        ) from error
    return payload


@router.get("/state/reflections/settings", response_model=ReflectionSettingsView)
def reflection_settings(request: Request) -> ReflectionSettingsView:
    runtime = request.app.state.runtime_settings
    return ReflectionSettingsView(enabled=runtime.reflections_enabled, min_significance=runtime.reflection_min_significance)


def require_active_session(request: Request, session_id: str) -> None:
    store = getattr(request.app.state, "timeline_store", None)
    if store is None:
        return
    active_session_id = store.active_session_id()
    if active_session_id is not None and session_id != active_session_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is no longer active")


async def require_active_session_async(request: Request, session_id: str) -> None:
    """Async-route variant that keeps the SQLite lookup off the event loop."""
    store = getattr(request.app.state, "timeline_store", None)
    if store is None:
        return
    active_session_id = await asyncio.to_thread(store.active_session_id)
    if active_session_id is not None and session_id != active_session_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is no longer active")


@router.post("/session")
async def open_session(request: Request) -> dict[str, object]:
    """Resume the active browser session without treating a reload as reset."""
    store = getattr(request.app.state, "timeline_store", None)
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Timeline V2 is disabled")
    return await asyncio.to_thread(store.ensure_active_session)


@router.post("/session/reset")
async def reset_session(request: Request) -> dict[str, object]:
    store = getattr(request.app.state, "timeline_store", None)
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Timeline V2 is disabled")
    previous_session_id = await asyncio.to_thread(store.active_session_id)
    if previous_session_id:
        coordinator = getattr(request.app.state, "turn_coordinator", None)
        if coordinator is not None:
            await coordinator.cancel_session(previous_session_id)
        await request.app.state.voice_session_manager.cancel(previous_session_id, notify=False)
        await request.app.state.speech_orchestrator.cancel_session(previous_session_id)
        voice_input = getattr(request.app.state, "voice_input_session_manager", None)
        if voice_input is not None:
            await voice_input.close_session(previous_session_id)
        service = getattr(request.app.state, "conversation_service", None)
        if service is not None:
            await service.close_session(previous_session_id)
    result = await asyncio.to_thread(store.reset_session)
    request.app.state.event_bus.publish(
        "conversation.session_reset", "warning", "Conversation session reset", result,
    )
    return result


@router.get("/debug/{session_id}")
def conversation_debug(session_id: str, request: Request) -> dict[str, object]:
    require_active_session(request, session_id)
    if not request.app.state.settings.conversation_diagnostics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    service = getattr(request.app.state, "conversation_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Conversation service unavailable")
    return service.debug(session_id)
