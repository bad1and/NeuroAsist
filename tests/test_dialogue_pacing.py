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
    assert "Простое согласие тоже полноценный ответ" in prompt
    assert "характер не требует мата или шутки" in prompt
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


@pytest.mark.parametrize("text", [
    "Прожарь меня за выбор темы редактора",
    "Ну, подколи меня по-дружески",
    "Можешь рассказать мне смешную шутку?",
    "Расскажи анекдот",
    "Давай пошути про мой баг",
    "Шуткани как-нибудь, чтобы меня разъебало со смеху",
    "Расскажи анекдотик",
])
def test_explicit_play_requests_get_punchline_pacing(text: str) -> None:
    pacing = infer_dialogue_pacing(text)
    assert pacing.mode == "banter"
    assert "не добавляй совет после панча" in pacing.prompt_block(input_mode="text")


@pytest.mark.parametrize("text", [
    "Объясни, что означает «прожарь меня»",
    "Вчера он сказал: прожарь меня",
    "Не шути сейчас, помоги с ошибкой",
    "Хватит подкалывать, я серьёзно",
    "Знаешь, откуда взялся этот мем?",
    "Подробно проанализируй, почему эта шутка смешная",
])
def test_mentions_and_serious_requests_do_not_activate_banter(text: str) -> None:
    assert infer_dialogue_pacing(text).mode != "banter"


def test_another_joke_followup_keeps_banter_without_inheriting_unrelated_offers():
    from apps.backend.app.llm.base import ChatMessage
    history = [ChatMessage(role="user", content="Шуткани что-нибудь"),
               ChatMessage(role="assistant", content="Неудачная шутка.")]
    assert infer_dialogue_pacing("Давай ещё какой-нибудь другой анекдотик", history).mode == "banter"
    history = [ChatMessage(role="user", content="Расскажи про RAM"),
               ChatMessage(role="assistant", content="RAM — оперативная память.")]
    assert infer_dialogue_pacing("Давай ещё что-нибудь", history).mode != "banter"


@pytest.mark.parametrize("text", [
    "Не понял, откуда в твоём анекдоте синяки?",
    "В чём смысл этого анекдота?",
    "Не понимаю этот анекдот",
])
def test_questions_about_a_previous_joke_do_not_request_another_joke(text: str) -> None:
    from apps.backend.app.llm.base import ChatMessage
    history = [ChatMessage(role="user", content="Расскажи анекдот")]
    assert infer_dialogue_pacing(text, history).mode != "banter"


@pytest.mark.parametrize("text", ["Здорово заебало", "Здорово, заебал", "Ну здорово заебал"])
def test_rough_greeting_is_a_greeting_instead_of_a_complaint(text: str) -> None:
    from apps.backend.app.agents.character.turn_intent import analyze_dialogue_turn
    assert analyze_dialogue_turn(text).kind == "greeting"
    assert infer_dialogue_pacing(text).mode == "micro"
