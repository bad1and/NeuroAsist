import json
from pathlib import Path

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.protocol import metadata_frame, parse_turn
from apps.backend.app.schemas.character import CharacterTurn, Emotion, Gesture, Intent


ROOT = Path(__file__).resolve().parents[1]


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
