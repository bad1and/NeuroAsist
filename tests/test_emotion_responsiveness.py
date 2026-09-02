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

    # User says something aggressive/insulting
    ctx = service.prepare(transcript="Пошёл нахуй отсюда", message_id="msg-profanity-1")
    assert ctx.state_applied is True
    assert ctx.appraisal.event_kind == "insult"
    assert ctx.appraisal.emotion_impulses.get("hurt", 0) > 0
    assert ctx.affect.hurt > 0 or ctx.affect.irritation > 0
    # Closeness should be reserved or distant
    assert ctx.behavior.closeness_policy in {"reserved", "distant"}
    assert ctx.behavior.avatar_emotion in {"sad", "annoyed", "angry"}


def test_praise_and_compliments_appraisal(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    ctx = service.prepare(transcript="Ирис ты молодец, всё супер и круто!", message_id="msg-praise-1")
    assert ctx.state_applied is True
    assert ctx.appraisal.event_kind == "praise"
    assert ctx.appraisal.emotion_impulses.get("joy", 0) >= 0.5
    assert ctx.affect.joy > 0.05
    assert ctx.behavior.avatar_emotion == "happy"
    assert ctx.behavior.expression_strength in {"subtle", "noticeable", "strong"}


def test_humor_and_laughter_appraisal(tmp_path: Path) -> None:
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    service = CharacterStateService(store)

    ctx = service.prepare(transcript="хахаха лол ору просто", message_id="msg-humor-1")
    assert ctx.state_applied is True
    assert ctx.appraisal.event_kind == "teasing"
    assert ctx.affect.playfulness > 0.25
    assert ctx.behavior.avatar_emotion == "smirk"


def test_sadness_and_vulnerability_appraisal(tmp_path: Path) -> None:
    engine = ConversationDecisionEngine()
    appraisal = engine.appraise("мне так плохо и одиноко, устал от всего", message_id="msg-sad-1")
    assert appraisal.event_kind == "vulnerability"
    assert appraisal.emotion_impulses.get("sadness", 0) > 0


def test_surprise_appraisal(tmp_path: Path) -> None:
    engine = ConversationDecisionEngine()
    appraisal = engine.appraise("ого ничего себе, вот это да!", message_id="msg-wow-1")
    assert appraisal.event_kind == "important_news"
    assert appraisal.emotion_impulses.get("interest", 0) > 0


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


def test_live_directive_expressive_fallback_catches_profanity_and_humor() -> None:
    # Annoyance on profanity
    d1 = make_live_directive_expressive(AvatarDirective(), "да пошёл ты нахуй")
    assert d1.emotion == Emotion.ANNOYED

    # Smirk on laughter
    d2 = make_live_directive_expressive(AvatarDirective(), "хахаха ору не могу")
    assert d2.emotion == Emotion.SMIRK

    # Happy on praise
    d3 = make_live_directive_expressive(AvatarDirective(), "ты просто красавица")
    assert d3.emotion == Emotion.HAPPY

    # Sad on distress
    d4 = make_live_directive_expressive(AvatarDirective(), "мне так грустно и паршиво")
    assert d4.emotion == Emotion.SAD


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
