from __future__ import annotations

from pydantic import ValidationError

from .schemas import (
    AckPayload,
    ClientStatePayload,
    HelloPayload,
    IncomingMessage,
    PlaybackPayload,
    PongPayload,
    PROTOCOL_VERSION,
)


class AvatarProtocolError(ValueError):
    """A client frame did not conform to Avatar protocol v1."""


_PAYLOADS = {
    "avatar.hello": HelloPayload,
    "avatar.pong": PongPayload,
    "avatar.ack": AckPayload,
    "avatar.playback.started": PlaybackPayload,
    "avatar.playback.finished": PlaybackPayload,
    "avatar.playback.failed": PlaybackPayload,
    "avatar.state.changed": ClientStatePayload,
}


def parse_incoming(raw: object) -> tuple[IncomingMessage, object]:
    if not isinstance(raw, dict):
        raise AvatarProtocolError("Avatar frame must be a JSON object")
    try:
        version = raw.get("protocol_version")
        if version != PROTOCOL_VERSION:
            raise AvatarProtocolError(
                f"Unsupported protocol_version {version!r}; expected {PROTOCOL_VERSION}"
            )
        envelope = IncomingMessage.model_validate(raw)
        payload_type = _PAYLOADS.get(envelope.type)
        if payload_type is None:
            raise AvatarProtocolError(f"Unknown avatar message type {envelope.type!r}")
        return envelope, payload_type.model_validate(envelope.payload)
    except ValidationError as exc:
        raise AvatarProtocolError("Malformed avatar message") from exc

