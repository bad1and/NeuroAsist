from __future__ import annotations

from pathlib import Path

from apps.backend.app.agents.character.agent import CharacterAgent, _ParseResult
from apps.backend.app.conversation.behavior import StateToBehaviorRenderer
from apps.backend.app.conversation.decision import ConversationDecisionEngine
from apps.backend.app.conversation.state import AffectState, CharacterStateReducer, ParticipantState
from apps.backend.app.conversation.state_service import CharacterStateService
from apps.backend.app.schemas.character import AffectCue, CharacterTurn, Emotion, Gesture, GestureCue
from apps.backend.app.storage.timeline import TimelineStore
from apps.backend.app.voice.directives import AvatarDirective, make_live_directive_expressive


def test_profanity_and_insult_appraisal(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    # User says something aggressive, but keywords do not mechanically trigger hurt
    ctx = service.prepare(transcript="Пошёл нахуй отсюда", message_id="msg-profanity-1")
    assert ctx.appraisal.event_kind == "neutral"

    # The AI model evaluates the turn and decides to be annoyed/distant
    service.record_assistant_turn(
        reply_text="Не смей разговаривать со мной в таком тоне.",
        emotion="annoyed",
        intensity=0.85,
    )
    current = service.current()
    assert current.affect.primary_emotion == "irritation"
    assert current.affect.irritation > 0


def test_praise_and_compliments_appraisal(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    # Keywords do not trigger praise automatically
    ctx = service.prepare(transcript="Ирис ты молодец, всё супер и круто!", message_id="msg-praise-1")
    assert ctx.appraisal.event_kind == "neutral"

    # The AI model responds with genuine joy
    service.record_assistant_turn(
        reply_text="Спасибо! Мне очень приятно это слышать :)",
        emotion="happy",
        intensity=0.8,
    )
    current = service.current()
    assert current.affect.primary_emotion == "joy"
    assert current.affect.joy > 0.3


def test_humor_and_laughter_appraisal(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    ctx = service.prepare(transcript="хахаха лол ору просто", message_id="msg-humor-1")
    assert ctx.appraisal.event_kind == "neutral"

    # The AI model chooses a playful smirk
    service.record_assistant_turn(
        reply_text="Ахах, ну ты выдал!",
        emotion="smirk",
        intensity=0.8,
    )
    current = service.current()
    assert current.affect.primary_emotion == "playfulness"
    assert current.affect.playfulness > 0.25


def test_sadness_and_vulnerability_appraisal(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    service.record_assistant_turn(
        reply_text="Мне очень жаль, что тебе сейчас так тяжело...",
        emotion="sad",
        intensity=0.7,
    )
    current = service.current()
    assert current.affect.primary_emotion == "sadness"
    assert current.affect.sadness > 0


def test_surprise_appraisal(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    service.record_assistant_turn(
        reply_text="Ого, вот это действительно неожиданный поворот!",
        emotion="thinking",
        intensity=0.8,
    )
    current = service.current()
    assert current.affect.primary_emotion == "interest"
    assert current.affect.interest > 0


def test_hybrid_arbitration_preserves_llm_emotion_when_state_is_neutral() -> None:
    renderer = StateToBehaviorRenderer()
    guide = renderer.render(AffectState(), ParticipantState())
    assert guide.avatar_emotion == "neutral"

    # LLM gave a happy emotion based on nuanced context
    turn = CharacterTurn(
        reply="Рада тебя слышать!",
        affect=AffectCue(emotion=Emotion.HAPPY, intensity=0.8),
        gesture=GestureCue(name=Gesture.TALK, intensity=0.7),
    )
    parsed = _ParseResult({"reply": "Рада тебя слышать!"}, valid=True, turn=turn)

    arbitrated = CharacterAgent._arbitrate_presentation(parsed, guide)
    assert arbitrated.turn is not None
    # Must preserve LLM's HAPPY emotion instead of forcing neutral
    assert arbitrated.turn.affect.emotion == Emotion.HAPPY


def test_live_directive_respects_llm_directive_without_keyword_triggers() -> None:
    # Live directive is preserved as chosen by the AI model without keyword overrides
    d1 = make_live_directive_expressive(AvatarDirective(emotion=Emotion.NEUTRAL), "да пошёл ты нахуй")
    assert d1.emotion == Emotion.NEUTRAL

    d2 = make_live_directive_expressive(AvatarDirective(emotion=Emotion.HAPPY), "да пошёл ты нахуй")
    assert d2.emotion == Emotion.HAPPY


def test_llm_emotion_overrides_non_neutral_state_emotion() -> None:
    renderer = StateToBehaviorRenderer()
    # State has non-neutral emotion (e.g. happy from praise trigger)
    guide = renderer.render(AffectState(joy=0.8), ParticipantState())
    assert guide.avatar_emotion == "happy"

    # LLM decided on an ironic smirk rather than scripted happy
    turn = CharacterTurn(
        reply="Ну-ну, рассказывай сказки.",
        affect=AffectCue(emotion=Emotion.SMIRK, intensity=0.75),
        gesture=GestureCue(name=Gesture.SHRUG, intensity=0.7),
    )
    parsed = _ParseResult({"reply": "Ну-ну, рассказывай сказки."}, valid=True, turn=turn)

    arbitrated = CharacterAgent._arbitrate_presentation(parsed, guide)
    assert arbitrated.turn is not None
    # LLM emotion (SMIRK) must win over state emotion (happy)
    assert arbitrated.turn.affect.emotion == Emotion.SMIRK
    # LLM gesture (SHRUG) must be preserved
    assert arbitrated.turn.gesture.name == Gesture.SHRUG


def test_llm_gesture_is_preserved_during_arbitration() -> None:
    renderer = StateToBehaviorRenderer()
    guide = renderer.render(AffectState(sadness=0.6), ParticipantState())
    # State would allow ("thinking", "talk", "shrug") with first being "thinking"

    turn = CharacterTurn(
        reply="Вот это да!",
        affect=AffectCue(emotion=Emotion.SURPRISED, intensity=0.9),
        gesture=GestureCue(name=Gesture.SURPRISE, intensity=0.85),
    )
    parsed = _ParseResult({"reply": "Вот это да!"}, valid=True, turn=turn)

    arbitrated = CharacterAgent._arbitrate_presentation(parsed, guide)
    assert arbitrated.turn is not None
    assert arbitrated.turn.affect.emotion == Emotion.SURPRISED
    assert arbitrated.turn.gesture.name == Gesture.SURPRISE


def test_live_directive_preserves_llm_emotion_even_with_trigger_words() -> None:
    # LLM explicitly generated smirk and shrug
    llm_directive = AvatarDirective(emotion=Emotion.SMIRK, gesture="shrug", intensity=0.8)

    # User text contains praise trigger words ("спасибо", "красавица")
    expressive = make_live_directive_expressive(llm_directive, "спасибо ты просто красавица")
    # Must preserve SMIRK instead of forcing HAPPY from trigger words
    assert expressive.emotion == Emotion.SMIRK
    assert expressive.gesture == "shrug"

    # User text contains profanity/aggression triggers ("пошёл нахуй")
    expressive2 = make_live_directive_expressive(llm_directive, "да пошёл ты нахуй")
    # Must preserve SMIRK instead of forcing ANNOYED
    assert expressive2.emotion == Emotion.SMIRK
    assert expressive2.gesture == "shrug"
