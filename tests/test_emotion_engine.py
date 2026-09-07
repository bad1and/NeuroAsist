from pathlib import Path

import pytest

from apps.backend.app.avatar.emotion_engine import EmotionEngine
from apps.backend.app.schemas.character import Emotion, Gesture


ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_mapping_covers_every_canonical_emotion() -> None:
    engine = EmotionEngine.from_path(ROOT / "apps/protocol/avatar-emotion-mapping.json")

    assert engine.mapping_valid is True
    assert set(engine.mapping) == set(Emotion)
    assert engine.mapping[Emotion.HAPPY].motion_profile == "energetic"


def test_invalid_mapping_uses_safe_default_and_reports_reason(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"neutral": {}}', encoding="utf-8")

    engine = EmotionEngine.from_path(path)

    assert engine.mapping_valid is False
    assert engine.mapping_error
    assert engine.state.target_emotion is Emotion.NEUTRAL


def test_metadata_is_idempotent_and_old_stop_cannot_reset_new_utterance() -> None:
    engine = EmotionEngine()
    first = engine.apply_metadata(
        emotion=Emotion.HAPPY, gesture=Gesture.GREETING, intensity=.8, utterance_id="first"
    )
    duplicate = engine.apply_metadata(
        emotion=Emotion.ANGRY, gesture=Gesture.FRUSTRATION, intensity=.9, utterance_id="first"
    )
    second = engine.apply_metadata(
        emotion=Emotion.THINKING, gesture=Gesture.QUESTION, intensity=.6, utterance_id="second"
    )
    stale_stop = engine.stop("first")

    assert duplicate == first
    assert second.generation == first.generation + 1
    assert stale_stop == second
    assert stale_stop.target_emotion is Emotion.THINKING
    assert stale_stop.speaking is True


def test_invalid_gesture_and_lower_priority_non_interrupting_gesture_do_not_disrupt_state() -> None:
    engine = EmotionEngine()
    state = engine.apply_metadata(
        emotion=Emotion.THINKING, gesture=Gesture.QUESTION, intensity=.7, utterance_id="u"
    )
    invalid = engine.apply_gesture(Gesture.GREETING, interrupt=False)
    lower = engine.apply_gesture(Gesture.AUTO, interrupt=False)

    assert state.gesture is Gesture.QUESTION
    assert invalid.gesture is Gesture.QUESTION
    assert lower.gesture is Gesture.QUESTION


def test_stop_returns_to_neutral_with_transition_parameters() -> None:
    engine = EmotionEngine()
    engine.apply_metadata(emotion=Emotion.SAD, gesture=Gesture.SHRUG, intensity=.7, utterance_id="u")
    stopped = engine.stop("u")

    assert stopped.target_emotion is Emotion.NEUTRAL
    assert stopped.gesture is Gesture.AUTO
    assert stopped.speaking is False
    assert stopped.release_ms > 0


def test_auto_gesture_resolves_cleanly_for_novel_and_micro_emotions() -> None:
    engine = EmotionEngine.from_path(ROOT / "apps/protocol/avatar-emotion-mapping.json")

    pouting = engine.apply_metadata(emotion=Emotion.POUTING, gesture=Gesture.AUTO, intensity=.8, utterance_id="1")
    assert pouting.gesture is Gesture.NONE

    wink = engine.apply_metadata(emotion=Emotion.WINK, gesture=Gesture.AUTO, intensity=.8, utterance_id="2", force=True)
    assert wink.gesture is Gesture.NONE

    teasing = engine.apply_metadata(emotion=Emotion.TEASING, gesture=Gesture.AUTO, intensity=.8, utterance_id="3", force=True)
    assert teasing.gesture is Gesture.NONE

    sleepy = engine.apply_metadata(emotion=Emotion.SLEEPY, gesture=Gesture.AUTO, intensity=.6, utterance_id="4", force=True)
    assert sleepy.gesture is Gesture.NONE

    thinking = engine.apply_metadata(emotion=Emotion.THINKING, gesture=Gesture.AUTO, intensity=.7, utterance_id="5", force=True)
    assert thinking.gesture is Gesture.THINKING_RIGHT

    confused = engine.apply_metadata(emotion=Emotion.CONFUSED, gesture=Gesture.AUTO, intensity=.7, utterance_id="6", force=True)
    assert confused.gesture is Gesture.SHRUG

    proud = engine.apply_metadata(emotion=Emotion.PROUD, gesture=Gesture.AUTO, intensity=.8, utterance_id="7", force=True)
    assert proud.gesture is Gesture.NOD


def test_explicit_hand_gestures_apply_under_any_emotion() -> None:
    engine = EmotionEngine.from_path(ROOT / "apps/protocol/avatar-emotion-mapping.json")

    # In pouting emotion, explicit greeting_right must succeed
    engine.apply_metadata(emotion=Emotion.POUTING, gesture=Gesture.AUTO, intensity=.8, utterance_id="1")
    right = engine.apply_gesture(Gesture.GREETING_RIGHT, interrupt=True)
    assert right.gesture is Gesture.GREETING_RIGHT

    # In thinking emotion, explicit greeting_left must succeed
    engine.apply_metadata(emotion=Emotion.THINKING, gesture=Gesture.AUTO, intensity=.7, utterance_id="2", force=True)
    left = engine.apply_gesture(Gesture.GREETING_LEFT, interrupt=True)
    assert left.gesture is Gesture.GREETING_LEFT

    # Explicit metadata gesture must not be overridden to none
    explicit_meta = engine.apply_metadata(
        emotion=Emotion.POUTING, gesture=Gesture.GREETING_RIGHT, intensity=.8, utterance_id="3", force=True
    )
    assert explicit_meta.gesture is Gesture.GREETING_RIGHT


def test_finish_speaking_preserves_target_emotion_for_neural_continuity() -> None:
    engine = EmotionEngine()
    engine.apply_metadata(emotion=Emotion.HAPPY, gesture=Gesture.GREETING_RIGHT, intensity=.85, utterance_id="u-1")
    assert engine.state.target_emotion is Emotion.HAPPY
    assert engine.state.speaking is True

    finished = engine.finish_speaking("u-1")
    assert finished.target_emotion is Emotion.HAPPY
    assert finished.intensity == .85
    assert finished.speaking is False
    assert finished.source_utterance_id is None


@pytest.mark.anyio
async def test_avatar_service_playback_finished_preserves_neural_emotion() -> None:
    from apps.backend.app.avatar.connection_manager import AvatarConnectionManager
    from apps.backend.app.avatar.protocol import parse_incoming
    from apps.backend.app.avatar.service import AvatarService
    from apps.backend.app.events.bus import EventBus

    class DummySocket:
        async def send_json(self, _msg: dict) -> None:
            pass

    manager = AvatarConnectionManager()
    client = await manager.register(DummySocket())
    service = AvatarService(manager, EventBus(), enabled=True, heartbeat_interval_seconds=10, client_timeout_seconds=30)

    # Start speech with neural emotion 'smirk'
    await service.speak(
        session_id="s1", utterance_id="utt-99", text="Шутка", audio_url="/test.wav",
        emotion="smirk", intent="casual_chat",
    )
    assert service.emotion_engine.state.target_emotion is Emotion.SMIRK
    assert service.emotion_engine.state.speaking is True

    # Playback finished from Unity
    envelope, payload = parse_incoming({
        "protocol_version": 1,
        "type": "avatar.playback.finished",
        "message_id": "m1",
        "timestamp": "2026-01-01T00:00:00Z",
        "session_id": "s1",
        "payload": {"utterance_id": "utt-99"},
    })
    await service.inbound(client.client_id, envelope, payload)

    # Must preserve SMIRK! Not wiped to neutral
    assert service.emotion_engine.state.target_emotion is Emotion.SMIRK
    assert service.emotion_engine.state.speaking is False


