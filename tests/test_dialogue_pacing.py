import pytest

from apps.backend.app.agents.character.dialogue_pacing import infer_dialogue_pacing


@pytest.mark.parametrize(
    "text",
    (
        "ага прям заебись",
        "ерисик привет",
        "это это смешно было ладно",
        "давай",
        "ну",
        "ну понятно",
        "окей",
        "ну блять это ебаный стт кривой так то я сказал стало",
        "как ты?",
    ),
)
def test_short_social_beats_get_micro_pacing(text: str) -> None:
    pacing = infer_dialogue_pacing(text)

    assert pacing.mode == "micro"
    prompt = pacing.prompt_block(input_mode="voice")
    assert "обычно одно предложение и до 12 слов" in prompt
    assert "Коротко не значит стерильно" in prompt
    assert "сохрани характер" in prompt
    assert "не список тем" in prompt


def test_long_personal_story_stays_conversational_instead_of_becoming_a_monologue() -> None:
    pacing = infer_dialogue_pacing(
        "Смотри, летом мы захотели тебя создать, Олег сначала сделал прототип интерфейса, "
        "потом я подхватил проект, и дальше всё понеслось-поехало."
    )

    assert pacing.mode == "conversational"
    prompt = pacing.prompt_block(input_mode="voice")
    assert "1-3 коротких предложения" in prompt
    assert "не пересказывай всю реплику" in prompt


@pytest.mark.parametrize(
    "text",
    (
        "Что ты помнишь об Олеге?",
        "У тебя появились новые записи в памяти?",
        "Расскажи, что сейчас в новостях России",
    ),
)
def test_questions_get_a_focused_but_bounded_answer(text: str) -> None:
    pacing = infer_dialogue_pacing(text)

    assert pacing.mode == "focused"
    prompt = pacing.prompt_block(input_mode="text")
    assert "2-5 предложений" in prompt
    assert "не превращает ответ в лекцию" in prompt


def test_explicit_depth_request_is_the_only_default_route_to_deep_mode() -> None:
    pacing = infer_dialogue_pacing("Подробно проанализируй архитектуру памяти и сравни варианты")

    assert pacing.mode == "deep"
    assert "явно просит подробный разбор" in pacing.prompt_block(input_mode="text")


def test_every_mode_rejects_the_repetitive_ai_response_formula() -> None:
    for text in ("окей", "я сегодня дома", "почему так?", "сделай подробный разбор"):
        assert "реакция + шутка + объяснение + вопрос" in infer_dialogue_pacing(text).prompt_block(
            input_mode="text"
        )


def test_pacing_limits_length_without_flattening_personality() -> None:
    for text in ("окей", "я сегодня дома", "почему так?", "сделай подробный разбор"):
        prompt = infer_dialogue_pacing(text).prompt_block(input_mode="text")
        assert "ограничивает длину, а не характер" in prompt
