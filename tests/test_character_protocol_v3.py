import json
from pathlib import Path

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.protocol import metadata_frame, parse_turn
from apps.backend.app.schemas.character import (
    CharacterTurn,
    DeliveryCue,
    DeliveryOverride,
    Emotion,
    Gesture,
    Intent,
)
from apps.backend.app.voice.delivery import SpeechEmphasis, SpeechPace, plan_speech


ROOT = Path(__file__).resolve().parents[1]


def test_delivery_overrides_apply_to_one_1_based_sentence_only() -> None:
    delivery = DeliveryCue(
        pace="normal",
        overrides=[
            DeliveryOverride(segment=2, pace="slow", emphasis="light"),
            DeliveryOverride(segment=3, pace="fast", emphasis="none"),
        ],
    )
    segments = plan_speech("Первая. Вторая! Третья?", delivery)

    assert [segment.pace for segment in segments] == [
        SpeechPace.NORMAL,
        SpeechPace.SLOW,
        SpeechPace.FAST,
    ]
    assert [segment.tempo for segment in segments] == [1.0, 0.95, 1.05]
    assert segments[1].emphasis is SpeechEmphasis.LIGHT
    assert segments[1].pause_before_ms == 35
    assert segments[2].emphasis is SpeechEmphasis.NONE


def test_delivery_override_can_set_precise_sentence_speed() -> None:
    delivery = DeliveryCue(
        overrides=[
            DeliveryOverride(segment=1, pace="normal", speed=0.82),
            DeliveryOverride(segment=2, pace="normal", speed=1.17),
        ],
    )

    segments = plan_speech("Медленнее. Быстрее.", delivery)

    assert [segment.tempo for segment in segments] == [0.82, 1.17]


def test_v3_turn_keeps_reply_when_only_metadata_is_invalid() -> None:
    turn, valid_metadata, reason = parse_turn(
        {
            "protocol_version": 3,
            "reply": "Текст должен остаться видимым.",
            "intent": "question",
            "affect": {"emotion": "not-an-emotion", "intensity": 5},
            "gesture": {"name": "auto", "intensity": 1, "interrupt": True},
            "delivery": {"pace": "normal", "emphasis": 0},
        },
        user_text="Почему это сломалось?",
    )

    assert valid_metadata is False
    assert reason == "invalid_metadata"
    assert turn.reply == "Текст должен остаться видимым."
    assert turn.affect.emotion is Emotion.THINKING
    assert turn.gesture.name is Gesture.QUESTION


def test_v1_v2_flat_payload_adapts_to_canonical_turn() -> None:
    turn, valid_metadata, reason = parse_turn(
        {"reply": "Окей", "emotion": "smirk", "intent": "casual_chat", "gesture": "shrug"}
    )

    assert valid_metadata is True
    assert reason == "legacy_adapter"
    assert turn.protocol_version == 3
    assert turn.affect.emotion is Emotion.SMIRK
    assert turn.gesture.name is Gesture.SHRUG


def test_metadata_frame_is_canonical_and_has_no_visible_reply() -> None:
    frame = metadata_frame(intent="question", emotion="thinking", gesture="question", intensity=.7)

    assert frame["protocol_version"] == 3
    assert frame["intent"] == "question"
    assert frame["affect"]["emotion"] == "thinking"
    assert "reply" not in frame


def test_invalid_v3_metadata_emits_diagnostic_without_losing_reply() -> None:
    events: list[tuple] = []
    agent = CharacterAgent(None, None, 0, event_publisher=lambda *args: events.append(args))

    result = agent._parse_response(
        '{"protocol_version":3,"reply":"Не теряй меня","intent":"question",'
        '"affect":{"emotion":"broken"},"gesture":{"name":"auto"},'
        '"delivery":{"pace":"normal","emphasis":0}}',
        session_id="s",
        user_text="Почему?",
    )

    assert result["reply"] == "Не теряй меня"
    assert result["emotion"] == "thinking"
    assert events[0][0] == "llm.invalid_json"
    assert events[0][3]["reason"] == "invalid_metadata"


def test_generated_python_typescript_csharp_and_json_schema_stay_in_parity() -> None:
    schema = json.loads((ROOT / "apps/protocol/character-turn.schema.json").read_text(encoding="utf-8"))
    typescript = (ROOT / "apps/web/src/generated/character-protocol.ts").read_text(encoding="utf-8")
    csharp = (ROOT / "apps/protocol/generated/csharp/CharacterProtocolV3.cs").read_text(encoding="utf-8")

    assert schema["$id"].endswith("character-turn-v3.json")
    assert schema["properties"]["protocol_version"]["default"] == 3
    for enum in (Emotion, Gesture, Intent):
        for item in enum:
            assert f'"{item.value}"' in typescript
            assert f'"{item.value}"' in csharp
    assert CharacterTurn.model_json_schema()["properties"]["reply"]["type"] == "string"


def test_avatar_directive_parsing_handles_quotes_and_brackets() -> None:
    from apps.backend.app.voice.directives import parse_avatar_directive

    d1 = parse_avatar_directive('[[avatar emotion="happy" gesture="greeting_right" intensity="0.85"]]')
    assert d1.emotion == Emotion.HAPPY
    assert d1.gesture == "greeting_right"
    assert abs(d1.intensity - 0.85) < 1e-4

    d2 = parse_avatar_directive('[avatar emotion=\'thinking\' gesture=\'nod\']')
    assert d2.emotion == Emotion.THINKING
    assert d2.gesture == "nod"

    d3 = parse_avatar_directive('[anim: greeting_left]')
    assert d3.gesture == "greeting_left"

    d4 = parse_avatar_directive('[gesture: shrug]')
    assert d4.gesture == "shrug"


def test_animation_directive_inference_handles_intent_and_morphs() -> None:
    from apps.backend.app.voice.directives import infer_animation_directive

    d_greet = infer_animation_directive("Привет!", "Привет-привет!")
    assert d_greet.gesture == "greeting_right"
    assert d_greet.emotion == Emotion.HAPPY

    d_quest = infer_animation_directive("Как твои дела?", "Всё отлично!")
    assert d_quest.gesture == "question_right"
    assert d_quest.emotion == Emotion.THINKING

    d_disagree = infer_animation_directive("Ты не права", "Да нет, погоди...")
    assert d_disagree.gesture == "disagreement"

    d_tease = infer_animation_directive(None, "Бе-бе-бе, не угадал!")
    assert d_tease.emotion == Emotion.TEASING
    assert d_tease.gesture == "none"

    d_wink = infer_animation_directive(None, "Сейчас всё сделаю, подмигиваю ;)")
    assert d_wink.emotion == Emotion.WINK
    assert d_wink.gesture == "none"

    d_scratch = infer_animation_directive("Почеши голову, пожалуйста", "Хм, дай подумать...")
    assert d_scratch.gesture == "head_scratch"
    assert d_scratch.emotion == Emotion.THINKING

    d_clap = infer_animation_directive("Похлопай мне", "Браво!")
    assert d_clap.gesture == "clapping"
    assert d_clap.emotion == Emotion.HAPPY

    d_laugh = infer_animation_directive("Посмейся", "Ха-ха-ха!")
    assert d_laugh.gesture == "laughing"
    assert d_laugh.emotion == Emotion.HAPPY

    d_thumbs = infer_animation_directive("Покажи класс", "Отличная работа!")
    assert d_thumbs.gesture == "thumbs_up"
    assert d_thumbs.emotion == Emotion.PROUD

    d_facepalm = infer_animation_directive("Фейспалм", "О боже мой...")
    assert d_facepalm.gesture == "facepalm"
    assert d_facepalm.emotion == Emotion.EMBARRASSED

    d_bow = infer_animation_directive("Сделай поклон", "Благодарю вас.")
    assert d_bow.gesture == "bow"

    d_point = infer_animation_directive("Укажи на экран", "Вот здесь.")
    assert d_point.gesture == "pointing"

    d_pout = infer_animation_directive(None, "Вот так всегда, надула губки...")
    assert d_pout.emotion == Emotion.POUTING
    assert d_pout.gesture == "none"


def test_speech_segment_resolves_auto_to_explicit_gesture() -> None:
    from apps.backend.app.voice.delivery import make_speech_segment, VoiceDirective

    # Without directive: should resolve to talk_right or inferred gesture, never "auto"
    seg1 = make_speech_segment("Я рассказываю интересную историю.")
    assert seg1.motion_gesture != "auto"
    assert seg1.motion_gesture in ("talk_right", "talk")

    # With directive gesture="auto": should also resolve away from "auto"
    seg2 = make_speech_segment("Что ты думаешь?", directive=VoiceDirective(gesture="auto"))
    assert seg2.motion_gesture != "auto"

    # Facial micro emotion: gesture should be none
    seg3 = make_speech_segment("Бе-бе!", directive=VoiceDirective(emotion="teasing", gesture="auto"))
    assert seg3.motion_gesture == "none"

    # Explicit gesture: preserved
    seg4 = make_speech_segment("Пока!", directive=VoiceDirective(gesture="farewell_right"))
    assert seg4.motion_gesture == "farewell_right"


def test_requested_action_never_uses_talk_gesture() -> None:
    from apps.backend.app.voice.directives import infer_animation_directive, LiveDirectiveParser

    # 1. User says "Помаши рукой" -> must be greeting_right and happy, never talk!
    d_wave = infer_animation_directive("Помаши рукой", "Вот, машу!")
    assert d_wave.gesture == "greeting_right"
    assert d_wave.emotion == Emotion.HAPPY

    d_wave2 = infer_animation_directive("Помахай ручкой, пожалуйста", "Привет-привет!")
    assert d_wave2.gesture == "greeting_right"
    assert d_wave2.emotion == Emotion.HAPPY

    # 2. In LiveDirectiveParser: header with neutral/auto or talk is overridden by requested action
    parser = LiveDirectiveParser(user_text="Помаши рукой")
    dir_parsed, _ = parser.feed('[[avatar emotion=neutral gesture=auto intensity=1.0]] Привет!')
    assert dir_parsed is not None
    assert dir_parsed.gesture == "greeting_right"
    assert dir_parsed.emotion == Emotion.HAPPY

    # 3. In parse_turn (JSON mode): if model returned generic "talk", it must be overridden
    turn, valid, _ = parse_turn(
        {
            "protocol_version": 3,
            "reply": "Смотри, машу тебе ручкой!",
            "intent": "casual_chat",
            "affect": {"emotion": "neutral"},
            "gesture": {"name": "talk"},
            "delivery": {"pace": "normal", "emphasis": 0},
        },
        user_text="Помаши рукой",
    )
    assert turn.gesture.name == Gesture.GREETING_RIGHT
    assert turn.affect.emotion == Emotion.HAPPY

    # 4. Nodding / shrug / wink requests
    d_nod = infer_animation_directive("Кивни головой", "Ага!")
    assert d_nod.gesture == "nod"

    d_shrug = infer_animation_directive("Пожми плечами", "Не знаю даже...")
    assert d_shrug.gesture == "shrug"

    d_wink = infer_animation_directive("Подмигни мне", "Лови подмигивание ;)")
    assert d_wink.emotion == Emotion.WINK
    assert d_wink.gesture == "none"

    # 5. Head scratch, clapping, laughing, thumbs up, facepalm, bow
    d_scratch = infer_animation_directive("Почеши голову, пожалуйста", "Хм, дай подумать...")
    assert d_scratch.gesture == "head_scratch"
    assert d_scratch.emotion == Emotion.THINKING

    d_scratch2 = infer_animation_directive("Почеши затылок", "Так-так...")
    assert d_scratch2.gesture == "head_scratch"
    assert d_scratch2.emotion == Emotion.THINKING

    d_clap = infer_animation_directive("Похлопай в ладоши", "Браво!")
    assert d_clap.gesture == "clapping"
    assert d_clap.emotion == Emotion.HAPPY

    d_laugh = infer_animation_directive("Посмейся", "Ха-ха-ха!")
    assert d_laugh.gesture == "laughing"
    assert d_laugh.emotion == Emotion.HAPPY

    d_thumbs = infer_animation_directive("Покажи класс", "Супер!")
    assert d_thumbs.gesture == "thumbs_up"
    assert d_thumbs.emotion == Emotion.PROUD

    d_facepalm = infer_animation_directive("Сделай фейспалм", "Ой всё...")
    assert d_facepalm.gesture == "facepalm"
    assert d_facepalm.emotion == Emotion.EMBARRASSED

    d_bow = infer_animation_directive("Поклонись мне", "Приветствую вас.")
    assert d_bow.gesture == "bow"
    assert d_bow.emotion == Emotion.NEUTRAL

    # 6. Override generic talk in parse_turn when user asked to scratch head
    turn_scratch, _, _ = parse_turn(
        {
            "protocol_version": 3,
            "reply": "Чешу затылок и думаю.",
            "intent": "casual_chat",
            "affect": {"emotion": "neutral"},
            "gesture": {"name": "talk"},
            "delivery": {"pace": "normal", "emphasis": 0},
        },
        user_text="Почеши голову",
    )
    assert turn_scratch.gesture.name == Gesture.HEAD_SCRATCH
    assert turn_scratch.affect.emotion == Emotion.THINKING



