import asyncio
import re
from pathlib import Path
from typing import get_args

import pytest

from apps.backend.app.avatar.body import BodyAction, BodyArguments, body_skill
from apps.backend.app.avatar.connection_manager import AvatarConnectionManager
from apps.backend.app.avatar.protocol import parse_incoming
from apps.backend.app.avatar.schemas import AckPayload, BodyActionResultPayload, IncomingMessage
from apps.backend.app.avatar.service import AvatarService
from apps.backend.app.events.bus import EventBus
from apps.backend.app.schemas.character import Gesture


class Socket:
    def __init__(self):
        self.sent = asyncio.Queue()

    async def send_json(self, message):
        await self.sent.put(message)


async def renderer():
    manager = AvatarConnectionManager()
    service = AvatarService(manager, EventBus(), enabled=True, heartbeat_interval_seconds=5, client_timeout_seconds=10)
    socket = Socket()
    client = await manager.register(socket)
    await manager.update(client.client_id, renderer_ready=True, body_actions=list(get_args(BodyAction)) + [g.value for g in Gesture if g not in {Gesture.NONE, Gesture.AUTO}])
    return service, client, socket


def test_body_capabilities_match_the_unity_contract():
    source = Path("apps/avatar-unity/Assets/NeuroAsistAvatar/Runtime/Motion/AvatarBodyController.cs").read_text(encoding="utf-8")
    manifest = source.split("BodyActions = {", 1)[1].split("};", 1)[0]
    assert set(re.findall(r'"([a-z_]+)"', manifest)) == set(get_args(BodyAction))


@pytest.mark.anyio
async def test_receipt_and_other_renderer_cannot_claim_a_measured_pose():
    service, client, socket = await renderer()
    task = asyncio.create_task(service.perform_body_action(session_id="body", action="raise_left_hand"))
    command = await socket.sent.get()
    identity = command["message_id"]
    ack = IncomingMessage(type="avatar.ack", payload={})
    await service.inbound(client.client_id, ack, AckPayload(reply_to=identity, accepted=True))
    await asyncio.sleep(0)
    assert not task.done()
    result = BodyActionResultPayload(reply_to=identity, action="raise_left_hand", reached=True, left_hand="raised", right_hand="rest")
    frame = IncomingMessage(type="avatar.action.result", payload={})
    await service.inbound("different-renderer", frame, result)
    assert not task.done()
    await service.inbound(client.client_id, frame, result.model_copy(update={"action": "raise_right_hand"}))
    assert not task.done()
    await service.inbound(client.client_id, frame, result)
    assert (await task)["reached"] is True
    assert not service._body_waiters


@pytest.mark.anyio
async def test_rejection_timeout_and_disconnection_are_not_successes():
    service, client, socket = await renderer()
    task = asyncio.create_task(service.perform_body_action(session_id="body", action="raise_right_hand"))
    command = await socket.sent.get()
    await service.inbound(client.client_id, IncomingMessage(type="avatar.ack", payload={}), AckPayload(reply_to=command["message_id"], accepted=False))
    assert (await task)["reason"] == "renderer_rejected"
    result = await service.perform_body_action(session_id="body", action="raise_right_hand", timeout=.01)
    assert result == {"action": "raise_right_hand", "reached": False, "reason": "renderer_timeout"}
    await service.manager.unregister(client.client_id)
    assert (await service.perform_body_action(session_id="body", action="blink"))["reason"] == "disconnected"
    assert not service._body_waiters


@pytest.mark.anyio
async def test_old_renderer_is_not_advertised_as_supporting_body_actions():
    service, client, _ = await renderer()
    await service.manager.update(client.client_id, body_actions=[])
    assert (await service.perform_body_action(session_id="body", action="blink_left"))["reason"] == "unsupported_renderer"


@pytest.mark.anyio
async def test_a_failed_step_stops_the_sequence_and_reports_partial_execution():
    class Service:
        calls = []
        async def perform_body_action(self, *, session_id, action):
            self.calls.append((session_id, action))
            return {"action": action, "reached": action == "raise_left_hand"}
        async def body_status(self):
            return {"connected": True}
    service = Service()
    tool = body_skill(service, lambda: "active-session")
    result = await tool.execute(BodyArguments(actions=[{"action": a} for a in ("raise_left_hand", "blink_left", "lower_left_hand")]))
    assert service.calls == [("active-session", "raise_left_hand"), ("active-session", "blink_left")]
    assert [item["reached"] for item in result["results"]] == [True, False]


def test_action_result_round_trips_and_emotion_does_not_invent_a_gesture():
    _, result = parse_incoming({"protocol_version": 2, "type": "avatar.action.result", "payload": {
        "reply_to": "measured", "action": "blink_right", "reached": True, "left_eye": 0, "right_eye": 0,
    }})
    assert result.reached
    from apps.backend.app.voice.directives import infer_animation_directive, parse_avatar_directive
    assert infer_animation_directive("", "Привет, я подняла руку и кивнула.").gesture == "auto"
    assert parse_avatar_directive("[[avatar emotion=happy]]").gesture == "auto"


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("reached", [False, True])
async def test_body_tool_result_reaches_the_model_in_json_and_voice_without_spoken_commands(live, reached):
    from apps.backend.app.agents.character.agent import CharacterAgent
    from tests.test_conversation_skills import ChunkedLLM, History, answer, command, response
    class Service:
        calls = []
        async def perform_body_action(self, *, session_id, action):
            self.calls.append((session_id, action))
            return {"action": action, "reached": reached, "reason": None if reached else "pose_not_reached"}
        async def body_status(self):
            return {"connected": True}
    call = {"name": "avatar_body", "arguments": {"actions": [{"action": "raise_left_hand"}]}}
    # A lying model response must be replaced before either chat or TTS sees it.
    reply = "Подняла левую руку."
    llm = ChunkedLLM([command(call, live), response(reply, live)], 5)
    service = Service()
    agent = CharacterAgent(llm, History(), 12, avatar_service=service)
    visible = await answer(agent, "Подними левую руку", live)
    if live:
        from apps.backend.app.voice.directives import clean_live_reply
        visible = clean_live_reply(visible)
    assert visible == (reply if reached else "Нужная поза не достигнута. Не буду говорить, что сделала.")
    assert service.calls == [("s", "raise_left_hand")]
    assert any('"reached": ' + str(reached).lower() in message.content for message in llm.calls[-1])
    assert agent.last_skill_metadata["name"] == "avatar_body"
    if not live:
        assert agent.last_turn.gesture.name == Gesture.NONE


@pytest.mark.parametrize("action", ["greeting_left", "head_scratch_right", "thumbs_up_left", "facepalm_right"])
def test_tool_accepts_semantic_gestures_with_an_explicit_hand(action):
    assert BodyArguments(actions=[{"action": action}]).actions[0].action == action


@pytest.mark.parametrize("action", ["auto", "none"])
def test_tool_rejects_automatic_gesture_instead_of_claiming_an_action(action):
    with pytest.raises(ValueError):
        BodyArguments(actions=[{"action": action}])


@pytest.mark.anyio
async def test_json_repair_cannot_reintroduce_a_gesture_after_the_tool_already_acted():
    import json
    from apps.backend.app.agents.character.agent import CharacterAgent
    from tests.test_conversation_skills import ChunkedLLM, History, answer, command
    class Service:
        async def perform_body_action(self, **kwargs): return {"action": "head_scratch_right", "reached": True}
        async def body_status(self): return {"connected": True}
    call = {"name": "avatar_body", "arguments": {"actions": [{"action": "head_scratch_right"}]}}
    invalid = {"reply": "Почесала голову правой рукой.", "affect": {"emotion": "invalid"}, "gesture": {"name": "head_scratch_right"}}
    repaired = {**invalid, "affect": {"emotion": "happy"}}
    llm = ChunkedLLM([command(call, False), json.dumps(invalid, ensure_ascii=False), json.dumps(repaired, ensure_ascii=False)], 5)
    agent = CharacterAgent(llm, History(), 12, avatar_service=Service())
    result = await answer(agent, "Почеши голову правой рукой", False)
    assert "Почесала" in result
    assert agent.last_turn.gesture.name == Gesture.NONE


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_timeout_never_claims_either_success_or_a_known_rest_pose(live):
    from apps.backend.app.agents.character.agent import CharacterAgent
    from tests.test_conversation_skills import ChunkedLLM, History, answer, command, response
    from apps.backend.app.voice.directives import clean_live_reply
    class Service:
        async def perform_body_action(self, **kwargs): return {"action": "raise_left_hand", "reached": False, "reason": "renderer_timeout"}
        async def body_status(self): return {"connected": True}
    call = {"name": "avatar_body", "arguments": {"actions": [{"action": "raise_left_hand"}]}}
    llm = ChunkedLLM([command(call, live), response("Подняла левую руку, точно поднята!", live)], 7)
    agent = CharacterAgent(llm, History(), 12, avatar_service=Service())
    visible = clean_live_reply(await answer(agent, "Подними левую руку", live))
    assert "подтверждения" in visible and "сейчас не знаю" in visible
    assert "точно" not in visible and "поднята" not in visible and "опущена" not in visible


def test_final_execution_guard_survives_a_missing_parsed_turn():
    from apps.backend.app.agents.character.agent import CharacterAgent, _ParseResult
    from tests.test_conversation_skills import ChunkedLLM, History
    agent = CharacterAgent(ChunkedLLM([], 5), History(), 12)
    agent.last_skill_metadata = {"name": "avatar_body", "status": "ok", "body_result": {
        "results": [{"action": "raise_left_hand", "reached": False, "reason": "renderer_timeout"}]}}
    result = agent._finalize_model_reply(_ParseResult({"reply": "Точно подняла!"}, False, "invalid", None),
        "s", "text", persist_reply=False, persist_reply_callback=None)
    assert "сейчас не знаю" in result["reply"]
    assert agent.last_turn.gesture.name == Gesture.NONE


@pytest.mark.anyio
@pytest.mark.parametrize("live", [False, True])
async def test_success_acknowledges_only_the_measured_action_and_keeps_model_emotion(live):
    import json
    from apps.backend.app.agents.character.agent import CharacterAgent
    from tests.test_conversation_skills import ChunkedLLM, History, answer, command
    from apps.backend.app.voice.directives import clean_live_reply
    class Service:
        async def perform_body_action(self, **kwargs): return {"action": "raise_left_hand", "reached": True}
        async def body_status(self): return {"connected": True}
    call = {"name": "avatar_body", "arguments": {"actions": [{"action": "raise_left_hand"}]}}
    invented = "Обе руки подняты, я вижу себя. Раз ты сказал, значит сделала."
    reply = "[[avatar emotion=happy gesture=greeting_right]] " + invented if live else json.dumps({"reply": invented, "emotion": "happy", "intent": "task_request", "gesture": "greeting_right"}, ensure_ascii=False)
    agent = CharacterAgent(ChunkedLLM([command(call, live), reply], 5), History(), 12, avatar_service=Service())
    visible = await answer(agent, "Подними левую руку", live)
    assert clean_live_reply(visible) == "Подняла левую руку."
    if live:
        assert "emotion=happy" in visible and "gesture=none" in visible
    else:
        assert agent.last_turn.affect.emotion.value == "happy"
        assert agent.last_turn.gesture.name == Gesture.NONE


def test_every_actual_command_has_a_factual_acknowledgement_and_empty_results_have_none():
    from apps.backend.app.avatar.body import ACTION_CONFIRMATIONS, measured_reply
    assert set(ACTION_CONFIRMATIONS) == set(get_args(BodyAction)) | {g.value for g in Gesture if g not in {Gesture.AUTO, Gesture.NONE}}
    assert "Не получила подтверждения" in measured_reply("ok", {"results": []})
    assert measured_reply("ok", {"results": [{"action": "raise_right_hand", "reached": True, "hold_seconds": 1}, {"action": "lower_right_hand", "reached": True}]}) == "Подняла правую руку, подержала 1 с, затем опустила правую руку."
