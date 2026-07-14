from pathlib import Path

import anyio
import pytest

from apps.backend.app.voice.input import VadGate, VadProvider, VoiceInputSessionManager


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class FakeVoiceService:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save_pcm16_temp(self, pcm16: bytes, sample_rate: int) -> Path:
        path = self.root / "input.wav"
        path.write_bytes(pcm16)
        return path

    def cleanup_upload(self, path: Path) -> None:
        path.unlink(missing_ok=True)


class SequenceVad(VadProvider):
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)

    def probability(self, pcm16: bytes, sample_rate: int) -> float:
        return next(self.values)


def test_vad_gate_debounces_transitions() -> None:
    gate = VadGate(threshold=.5, start_ms=100, end_ms=200)
    assert gate.feed(.8, 0) is None
    assert gate.feed(.8, .1) == "speech_started"
    assert gate.feed(0, .2) is None
    assert gate.feed(0, .4) == "speech_ended"


@pytest.mark.anyio
async def test_pcm_input_uses_ram_ring_and_removes_temp_stt_file(tmp_path: Path) -> None:
    handled: list[tuple[str, bytes, str]] = []
    barge: list[str] = []

    async def on_utterance(session_id, path, language, connection) -> None:
        handled.append((session_id, path.read_bytes(), language))
        await connection.send({"type": "voice.input.transcript", "transcript": "привет"})

    async def on_speech_started(session_id: str) -> None:
        barge.append(session_id)

    manager = VoiceInputSessionManager(
        FakeVoiceService(tmp_path), on_utterance, on_speech_started,
        vad=SequenceVad([.9, .9, 0, 0]), pre_roll_ms=500,
    )
    socket = FakeSocket()
    await manager.register("s", socket)
    await manager.start("s", sample_rate=16000, channels=1, language="ru")
    session = manager._sessions["s"]
    session.gate.start_ms = 0
    session.gate.end_ms = 0
    frame = b"\x01\x00" * 160
    for _ in range(4):
        await manager.feed("s", frame)
    await anyio.sleep(.05)

    assert barge == ["s"]
    assert handled and handled[0][0] == "s"
    assert handled[0][1].startswith(frame)
    assert not (tmp_path / "input.wav").exists()
    assert [item["type"] for item in socket.sent] == [
        "voice.input.ready", "voice.input.speech_started", "voice.input.finalizing", "voice.input.transcript",
    ]
