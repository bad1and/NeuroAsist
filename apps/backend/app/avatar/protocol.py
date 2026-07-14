from __future__ import annotations

from pydantic import ValidationError

from .schemas import (
    AckPayload,
    ClientStatePayload,
    GesturePayload,
    MotionProfilePayload,
    HelloPayload,
    IncomingMessage,
    PlaybackPayload,
    PongPayload,
    StreamReceiptPayload,
    SUPPORTED_PROTOCOL_VERSIONS,
)


class AvatarProtocolError(ValueError):
    """A client frame did not conform to a supported Avatar protocol."""


_PAYLOADS = {
    "avatar.hello": HelloPayload,
    "avatar.pong": PongPayload,
    "avatar.ack": AckPayload,
    "avatar.playback.started": PlaybackPayload,
    "avatar.playback.finished": PlaybackPayload,
    "avatar.playback.failed": PlaybackPayload,
    "avatar.state.changed": ClientStatePayload,
    "avatar.gesture.started": GesturePayload,
    "avatar.gesture.finished": GesturePayload,
    "avatar.gesture.failed": GesturePayload,
    "avatar.motion_profile_changed": MotionProfilePayload,
    "avatar.stream.received": StreamReceiptPayload,
}


def parse_incoming(raw: object) -> tuple[IncomingMessage, object]:
    if not isinstance(raw, dict):
        raise AvatarProtocolError("Avatar frame must be a JSON object")
    try:
        version = raw.get("protocol_version")
        if version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise AvatarProtocolError(
                f"Unsupported protocol_version {version!r}; expected one of {SUPPORTED_PROTOCOL_VERSIONS}"
            )
        envelope = IncomingMessage.model_validate(raw)
        payload_type = _PAYLOADS.get(envelope.type)
        if payload_type is None:
            raise AvatarProtocolError(f"Unknown avatar message type {envelope.type!r}")
        return envelope, payload_type.model_validate(envelope.payload)
    except ValidationError as exc:
        raise AvatarProtocolError("Malformed avatar message") from exc
