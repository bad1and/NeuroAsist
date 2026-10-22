import pytest
from pydantic import ValidationError

from apps.backend.app.avatar.connection_manager import AvatarConnectionManager
from apps.backend.app.avatar.protocol import parse_incoming
from apps.backend.app.avatar.schemas import AvatarPresentationRequest
from apps.backend.app.avatar.service import AvatarService
from apps.backend.app.events.bus import EventBus


class Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, frame):
        self.sent.append(frame)


def service_for(manager):
    return AvatarService(manager, EventBus(), enabled=True,
                         heartbeat_interval_seconds=30, client_timeout_seconds=60)


@pytest.mark.anyio
async def test_old_welcome_request_cannot_replace_active_dialog_presentation():
    manager = AvatarConnectionManager()
    client = await manager.register(Socket())
    await manager.update(client.client_id, protocol_version=2)
    service = service_for(manager)
    await service.set_presentation("portrait", 20)
    result = await service.set_presentation("welcome_seated", 19)
    assert result.skipped
    assert [frame["payload"]["presentation"] for frame in client.websocket.sent] == ["portrait"]


@pytest.mark.anyio
async def test_renderer_receives_latest_presentation_after_reconnect():
    manager = AvatarConnectionManager()
    service = service_for(manager)
    await service.set_presentation("welcome_seated", 1)
    await service.set_presentation("portrait", 2)
    client = await manager.register(Socket())
    envelope, payload = parse_incoming({"protocol_version": 2, "type": "avatar.ready",
                                       "message_id": "ready", "payload": {}})
    await service.inbound(client.client_id, envelope, payload)
    assert client.websocket.sent[-1]["type"] == "avatar.presentation"
    assert client.websocket.sent[-1]["payload"] == {"presentation": "portrait"}


def test_presentation_request_rejects_unknown_modes_and_missing_revision():
    with pytest.raises(ValidationError):
        AvatarPresentationRequest(mode="dance", revision=1)
    with pytest.raises(ValidationError):
        AvatarPresentationRequest(mode="portrait")


def test_presentation_endpoint_validates_and_keeps_transient_state():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.backend.app.api.routes.avatar import router

    app = FastAPI()
    app.include_router(router)
    app.state.avatar_service = service_for(AvatarConnectionManager())
    with TestClient(app) as client:
        assert client.post("/avatar/presentation", json={"mode": "dance", "revision": 1}).status_code == 422
        response = client.post("/avatar/presentation", json={"mode": "welcome_seated", "revision": 2})
        assert response.status_code == 200
        assert app.state.avatar_service._presentation == "welcome_seated"
        client.post("/avatar/presentation", json={"mode": "portrait", "revision": 1})
        assert app.state.avatar_service._presentation == "welcome_seated"
