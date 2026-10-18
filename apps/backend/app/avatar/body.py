"""Model-facing body control with measured renderer results, not dispatch receipts."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from apps.backend.app.schemas.character import Gesture
from apps.backend.app.skills.runtime import Skill

BodyAction = Literal[
    "raise_left_hand", "raise_right_hand", "raise_both_hands",
    "lower_left_hand", "lower_right_hand", "lower_both_hands",
    "extend_left_hand", "extend_right_hand", "extend_both_hands",
    "tilt_head_left", "tilt_head_right", "turn_head_left", "turn_head_right",
    "look_up", "look_down", "head_neutral", "blink_left", "blink_right", "blink",
    "close_left_eye", "close_right_eye", "close_eyes",
    "open_left_eye", "open_right_eye", "open_eyes", "body_neutral", "body_status",
]

BodyGesture = Enum(
    "BodyGesture", {g.name: g.value for g in Gesture if g not in {Gesture.AUTO, Gesture.NONE}}, type=str,
)

ACTION_CONFIRMATIONS = {
    "raise_left_hand": "Подняла левую руку", "raise_right_hand": "Подняла правую руку", "raise_both_hands": "Подняла обе руки",
    "lower_left_hand": "Опустила левую руку", "lower_right_hand": "Опустила правую руку", "lower_both_hands": "Опустила обе руки",
    "extend_left_hand": "Протянула левую руку", "extend_right_hand": "Протянула правую руку", "extend_both_hands": "Протянула обе руки",
    "tilt_head_left": "Наклонила голову влево", "tilt_head_right": "Наклонила голову вправо",
    "turn_head_left": "Повернула голову влево", "turn_head_right": "Повернула голову вправо",
    "look_up": "Приподняла голову", "look_down": "Опустила голову", "head_neutral": "Выпрямила голову",
    "blink_left": "Подмигнула левым глазом", "blink_right": "Подмигнула правым глазом", "blink": "Моргнула обоими глазами",
    "close_left_eye": "Закрыла левый глаз", "close_right_eye": "Закрыла правый глаз", "close_eyes": "Закрыла глаза",
    "open_left_eye": "Открыла левый глаз", "open_right_eye": "Открыла правый глаз", "open_eyes": "Открыла глаза",
    "body_neutral": "Вернулась в спокойную позу", "body_status": "Проверила положение аватара",
}
_GESTURE_CONFIRMATIONS = {
    "talk": "Сделала разговорный жест{hand}", "greeting": "Помахала{hand}",
    "farewell": "Помахала{hand} на прощание", "agreement": "Кивнула", "disagreement": "Покачала головой",
    "question": "Сделала вопросительный жест{hand}", "explanation": "Сделала поясняющий жест{hand}",
    "thinking": "Сделала задумчивый жест{hand}", "surprise": "Сделала жест удивления",
    "frustration": "Сделала жест досады", "shrug": "Пожала плечами", "nod": "Кивнула",
    "head_scratch": "Почесала голову{hand}", "clapping": "Похлопала в ладоши", "laughing": "Сделала жест смеха",
    "thumbs_up": "Показала жест «класс»{hand}", "facepalm": "Сделала фейспалм{hand}",
    "pointing": "Указала{hand}", "bow": "Поклонилась",
}
for _gesture in BodyGesture:
    _name = _gesture.value
    _base, _, _side = _name.rpartition("_")
    if _side not in {"left", "right", "casual"}: _base, _side = _name, ""
    ACTION_CONFIRMATIONS[_name] = _GESTURE_CONFIRMATIONS[_base].format(
        hand=" левой рукой" if _side == "left" else " правой рукой" if _side == "right" else "")


def action_succeeded(status: str, value: object) -> bool:
    if status != "ok" or not isinstance(value, dict): return False
    results = value.get("results", [])
    return bool(results) and all(r.get("reached") for r in results) and any(r.get("action") != "body_status" for r in results)


class BodyStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: BodyAction | BodyGesture
    hold_seconds: float = Field(
        default=0, ge=0, le=3,
        description="Pause after completion. Hand/head/eyelid poses stay held until another command; one-shot gestures return to idle.",
    )

class BodyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[BodyStep] = Field(
        default_factory=list, max_length=6,
        description="Ordered actions. Empty list requests a fresh measured status from Unity.",
    )

def body_skill(service, session_id: str | Callable[[], str]) -> Skill:
    async def execute(arguments: BodyArguments):
        results = []
        for step in arguments.actions or [BodyStep(action="body_status")]:
            active_session = session_id() if callable(session_id) else session_id
            result = await service.perform_body_action(session_id=active_session, action=step.action)
            results.append(result)
            if not result.get("reached"):
                break
            if step.hold_seconds:
                await asyncio.sleep(step.hold_seconds)
                result["hold_seconds"] = step.hold_seconds
        renderer = await service.body_status()
        return {"results": results, "renderer": {"connected": renderer.get("connected", False)}}

    return Skill(
        "avatar_body",
        "Управляй своим аватаром: подними/опусти/протяни левую, правую или обе руки; наклони/поверни голову; моргни отдельным глазом, закрой/открой глаза. "
        "Лево/право — твоя анатомическая сторона. Позы удерживаются между репликами до опускания/head_neutral/body_neutral. "
        "Помаши рукой = greeting_left/right (wave); поднять/опустить = raise/lower, это разные действия. "
        "Почеши голову = head_scratch_left/right; класс = thumbs_up_left/right; укажи = pointing_left/right; фейспалм = facepalm_left/right; кивни = nod; хлопай = clapping; поклон = bow. Доступны и остальные Gesture. "
        "До 6 действий по порядку, hold_seconds — пауза. Для состояния actions=[]. "
        "Обязательно вызывай при просьбе выполнить действие телом или проверить выполнение. "
        "reached=true означает измеренную позу в Unity; sent/ack не доказывают выполнение. При ошибке признай её без выдуманных причин.",
        BodyArguments, execute, lambda: True, timeout_seconds=150,
    )


def measured_reply(status: str, value: object) -> str:
    """Keep missing evidence and pose checks factual in both text and TTS."""
    if status != "ok" or not isinstance(value, dict) or not value.get("results"):
        return "Не получила подтверждения от аватара. Не могу утверждать, что движение выполнено."
    results = value.get("results", [])
    failed = next((item for item in results if not item.get("reached")), None)
    if failed is not None:
        reason = failed.get("reason")
        if reason in {"disconnected", "disabled"}:
            return "Сейчас аватар не подключён, поэтому выполнить движение не получилось."
        if reason == "unsupported_renderer":
            return "Подключённая версия аватара не поддерживает это движение."
        if reason == "renderer_rejected":
            return "Аватар не принял команду на движение."
        if reason == "pose_not_reached":
            return "Нужная поза не достигнута. Не буду говорить, что сделала."
        return "Не получила подтверждения движения от аватара. Выполнилось ли оно — сейчас не знаю."
    if len(results) == 1 and results[0].get("action") == "body_status":
        result = results[0]
        names = {"raised": "поднята", "extended": "вытянута вперёд", "rest": "опущена", "moving": "ещё движется"}
        left = names.get(result.get("left_hand"), "не определена")
        right = names.get(result.get("right_hand"), "не определена")
        head = []
        if abs(result.get("head_roll", 0)) > 4:
            head.append("наклонена влево" if result["head_roll"] > 0 else "наклонена вправо")
        if abs(result.get("head_yaw", 0)) > 8:
            head.append("повёрнута влево" if result["head_yaw"] < 0 else "повёрнута вправо")
        if abs(result.get("head_pitch", 0)) > 8:
            head.append("опущена" if result["head_pitch"] > 0 else "приподнята")
        eyes = [side for side, key in (("левый", "left_eye"), ("правый", "right_eye")) if result.get(key, 0) > .8]
        eye_text = "глаза открыты" if not eyes else "оба глаза закрыты" if len(eyes) == 2 else f"{eyes[0]} глаз закрыт"
        return (f"На момент проверки аватар сообщает: левая рука {left}, правая {right}; "
                f"голова {' и '.join(head) if head else 'ровно'}, {eye_text}. Само изображение на твоём экране я не вижу.")
    phrases = []
    for result in results:
        phrase = ACTION_CONFIRMATIONS.get(result.get("action"), "Движение выполнено")
        hold = result.get("hold_seconds", 0)
        if isinstance(hold, (int, float)) and hold > 0:
            phrase += f", подержала {hold:g} с"
        phrases.append(phrase)
    return ", затем ".join(phrase if i == 0 else phrase[0].lower() + phrase[1:] for i, phrase in enumerate(phrases)) + "."
