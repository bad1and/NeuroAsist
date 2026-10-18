import pytest

from apps.backend.app.avatar.schemas import (
    GesturePayload, SpeakPayload, StreamMotionCuePayload,
)
from apps.backend.app.schemas.character import Emotion, Gesture
from apps.backend.app.avatar.emotion_engine import EmotionEngine
from apps.backend.app.voice.delivery import VoiceDirective, make_speech_segment
from apps.backend.app.voice.directives import infer_animation_directive


@pytest.mark.parametrize("gesture", list(Gesture))
def test_every_character_gesture_reaches_all_avatar_commands(gesture: Gesture) -> None:
    assert GesturePayload(gesture=gesture).gesture == gesture.value
    assert StreamMotionCuePayload(gesture=gesture).gesture == gesture.value
    assert SpeakPayload(
        utterance_id="motion", text="Проверка", audio_url="/audio.wav", gesture=gesture
    ).gesture == gesture.value


def test_unspecified_speech_leaves_hand_and_rhythm_to_renderer() -> None:
    for sequence in (0, 1, 7):
        assert make_speech_segment("Результат сохранён в каталоге.", sequence=sequence).motion_gesture == "auto"
    assert infer_animation_directive(None, "Результат сохранён в каталоге.").gesture == "auto"


def test_none_is_preserved_even_for_emotional_or_action_text() -> None:
    segment = make_speech_segment("Привет!", directive=VoiceDirective(gesture="none"))
    assert segment.motion_gesture == "none"


def test_happy_expression_does_not_imply_a_wave() -> None:
    assert infer_animation_directive("Улыбнись", "Хорошо.").gesture == "none"
    state = EmotionEngine().apply_metadata(
        emotion=Emotion.HAPPY, gesture=Gesture.AUTO, intensity=.8, utterance_id="smile"
    )
    assert state.gesture is Gesture.AUTO


@pytest.mark.parametrize("emotion", [Emotion.THINKING, Emotion.PROUD, Emotion.CONFUSED, Emotion.SURPRISED])
def test_emotion_alone_does_not_request_a_semantic_action(emotion: Emotion) -> None:
    state = EmotionEngine().apply_metadata(
        emotion=emotion, gesture=Gesture.AUTO, intensity=.7, utterance_id="mood"
    )
    assert state.gesture is Gesture.AUTO
