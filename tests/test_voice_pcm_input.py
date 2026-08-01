import asyncio
from pathlib import Path

import anyio
import pytest

from apps.backend.app.voice.input import (
    SileroVadProvider,
    VadGate,
    VadProvider,
    VoiceInputSessionManager,
)


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


class _FakeSileroModel:
    def eval(self):
        return self

    def reset_states(self) -> None:
        return None


def test_silero_vad_provider_stays_ready_after_the_first_session() -> None:
    # Bypass the loader so the regression test focuses on provider lifecycle:
    # one warm model is consumed by session one, then session two must get a
    # freshly loaded isolated model instead of energy fallback.
    provider = object.__new__(SileroVadProvider)
    provider._first_model = _FakeSileroModel()
    provider._model_path = None
    provider._package_loader = lambda *, onnx: _FakeSileroModel()
    provider._torch = object()
    provider.error = None

    first = provider.create_stream()
    second = provider.create_stream()

    assert first.name == "silero"
    assert second.name == "silero"
    assert provider.ready is True


class ControlledTurnDetector:
    ready = True
    name = "controlled"
    error = None

    def __init__(self, results: list[bool], block_first: bool = False) -> None:
        self.results = iter(results)
        self.block_first = block_first
        self.calls: list[bytes] = []
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def analyze(self, pcm16: bytes, sample_rate: int):
        from apps.backend.app.conversation.turn import TurnDetectionResult

        self.calls.append(pcm16)
        complete = next(self.results)
        if self.block_first and len(self.calls) == 1:
            self.first_started.set()
            await self.release_first.wait()
        return TurnDetectionResult(
            complete=complete,
            confidence=.9,
            provider=self.name,
            latency_ms=1,
        )


def test_vad_gate_debounces_transitions() -> None:
    gate = VadGate(threshold=.5, start_ms=100, end_ms=200)
    assert gate.feed(.8, 0) is None
    assert gate.feed(.8, .1) == "speech_started"
    assert gate.feed(0, .2) is None
    assert gate.feed(0, .4) == "speech_ended"


def test_vad_gate_clears_pending_silence_when_quiet_speech_resumes() -> None:
    gate = VadGate(start_threshold=.55, end_threshold=.35, start_ms=64, end_ms=320)
    assert gate.feed(.8, 512) is None
    assert gate.feed(.8, 512) == "speech_started"
    assert gate.feed(.2, 512) is None
    # A quieter syllable can stay below the start threshold while still being
    # above the end threshold. It must reset the pending endpoint timer.
    assert gate.feed(.4, 512) is None
    assert gate.state == "speech"
    assert all(gate.feed(.2, 512) is None for _ in range(9))
    assert gate.feed(.2, 512) == "speech_ended"


def test_pre_roll_keeps_tail_of_an_oversized_pcm_frame(tmp_path: Path) -> None:
    manager = VoiceInputSessionManager(FakeVoiceService(tmp_path), lambda *_args: None, pre_roll_ms=500)
    socket = FakeSocket()
    asyncio.run(manager.register("pre-roll", socket))
    input_session = manager._sessions["pre-roll"]
    input_session.sample_rate = 16_000
    oversized = bytes(range(256)) * 100

    manager._append_ring(input_session, oversized)

    assert input_session.ring_bytes == 16_000
    assert b"".join(input_session.ring) == oversized[-16_000:]


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


@pytest.mark.anyio
async def test_stop_flushes_confirmed_active_utterance_before_returning(tmp_path: Path) -> None:
    handled: list[bytes] = []

    async def on_utterance(session_id, path, language, connection) -> None:
        handled.append(path.read_bytes())

    manager = VoiceInputSessionManager(
        FakeVoiceService(tmp_path),
        on_utterance,
        vad=SequenceVad([.9]),
    )
    socket = FakeSocket()
    await manager.register("stop", socket)
    await manager.start("stop", sample_rate=16_000, channels=1, language="ru")
    manager._sessions["stop"].gate.start_ms = 0
    frame = b"\x07\x00" * 320

    await manager.feed("stop", frame)
    await manager.stop("stop")

    assert handled == [frame]
    assert not (tmp_path / "input.wav").exists()


@pytest.mark.anyio
async def test_continuation_during_endpoint_inference_keeps_entire_turn(tmp_path: Path) -> None:
    handled: list[bytes] = []
    generation = 0
    detector = ControlledTurnDetector([False, True], block_first=True)

    async def on_utterance(session_id, path, language, connection) -> None:
        handled.append(path.read_bytes())

    async def on_speech_started(session_id: str) -> int:
        nonlocal generation
        generation += 1
        return generation

    manager = VoiceInputSessionManager(
        FakeVoiceService(tmp_path),
        on_utterance,
        on_speech_started,
        vad=SequenceVad([.9, .9, 0, 0, .9, .9, 0, 0]),
        turn_detector=detector,
    )
    socket = FakeSocket()
    await manager.register("s", socket, version=2)
    await manager.start(
        "s",
        sample_rate=16000,
        channels=1,
        language="ru",
        mode="live_conversation",
    )
    session = manager._sessions["s"]
    session.gate.start_ms = 0
    session.gate.end_ms = 0
    first = b"\x01\x00" * 160
    second = b"\x02\x00" * 160

    for _ in range(4):
        await manager.feed("s", first)
    await detector.first_started.wait()
    for _ in range(4):
        await manager.feed("s", second)
    detector.release_first.set()
    await anyio.sleep(.05)

    assert len(handled) == 1
    assert handled[0].startswith(first)
    assert handled[0].endswith(second)
    assert len(handled[0]) >= 8 * len(first)


@pytest.mark.anyio
async def test_incomplete_turn_is_forced_complete_after_silence(tmp_path: Path) -> None:
    handled: list[bytes] = []
    detector = ControlledTurnDetector([False])

    async def on_utterance(session_id, path, language, connection) -> None:
        handled.append(path.read_bytes())

    manager = VoiceInputSessionManager(
        FakeVoiceService(tmp_path),
        on_utterance,
        vad=SequenceVad([.9, .9, 0, 0]),
        turn_detector=detector,
        max_turn_silence_ms=100,
    )
    socket = FakeSocket()
    await manager.register("s", socket, version=2)
    await manager.start(
        "s",
        sample_rate=16000,
        channels=1,
        language="ru",
        mode="live_conversation",
    )
    session = manager._sessions["s"]
    session.gate.start_ms = 0
    session.gate.end_ms = 0
    frame = b"\x03\x00" * 160
    for _ in range(4):
        await manager.feed("s", frame)
    await anyio.sleep(.15)

    assert handled == [frame * 4]
    forced = [
        event for event in socket.sent
        if event["type"] == "conversation.turn_completed"
        and event.get("provider") == "forced-timeout"
    ]
    assert len(forced) == 1


@pytest.mark.anyio
async def test_short_noise_during_iris_speech_does_not_barge_in(tmp_path: Path) -> None:
    handled: list[bytes] = []
    interrupted: list[str] = []

    async def on_utterance(session_id, path, language, connection) -> None:
        handled.append(path.read_bytes())

    async def on_speech_started(session_id: str) -> int:
        interrupted.append(session_id)
        return 1

    manager = VoiceInputSessionManager(
        FakeVoiceService(tmp_path),
        on_utterance,
        on_speech_started,
        vad=SequenceVad([.9, .9, 0, 0]),
        barge_in_guard=lambda _session_id: True,
        barge_in_confirmation_ms=100,
    )
    socket = FakeSocket()
    await manager.register("s", socket, version=2)
    await manager.start(
        "s",
        sample_rate=16000,
        channels=1,
        language="ru",
        mode="live_conversation",
    )
    session = manager._sessions["s"]
    session.gate.start_ms = 0
    session.gate.end_ms = 0
    frame = b"\x04\x00" * 160
    for _ in range(4):
        await manager.feed("s", frame)

    assert interrupted == []
    assert handled == []
    assert any(event["type"] == "conversation.noise_ignored" for event in socket.sent)


@pytest.mark.anyio
async def test_sustained_speech_during_iris_turn_confirms_barge_in(tmp_path: Path) -> None:
    interrupted: list[str] = []

    async def on_utterance(session_id, path, language, connection) -> None:
        return None

    async def on_speech_started(session_id: str) -> int:
        interrupted.append(session_id)
        return 3

    manager = VoiceInputSessionManager(
        FakeVoiceService(tmp_path),
        on_utterance,
        on_speech_started,
        vad=SequenceVad([.9, .9, .9]),
        barge_in_guard=lambda _session_id: True,
        barge_in_confirmation_ms=100,
    )
    socket = FakeSocket()
    await manager.register("s", socket, version=2)
    await manager.start(
        "s",
        sample_rate=16000,
        channels=1,
        language="ru",
        mode="live_conversation",
    )
    session = manager._sessions["s"]
    session.gate.start_ms = 0
    frame = b"\x05\x00" * 160
    await manager.feed("s", frame)
    await manager.feed("s", frame)
    await anyio.sleep(.11)
    await manager.feed("s", frame)

    assert interrupted == ["s"]
    assert session.connection.generation == 3
    assert any(event["type"] == "voice.input.speech_started" for event in socket.sent)
