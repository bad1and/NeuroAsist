from pathlib import Path

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
