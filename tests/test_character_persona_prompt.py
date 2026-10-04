import json
from pathlib import Path

from apps.backend.app.agents.character.persona import get_persona
from apps.backend.app.agents.character.prompts import (
    character_json_prompt,
    character_live_prompt,
    character_state_prompt,
    character_static_prefix,
)


def test_default_persona_requires_adaptive_conversational_replies() -> None:
    persona = get_persona("default")

    assert persona.display_name == "Iris"
    assert persona.persona_version == 8
    assert "Ты — Iris" in persona.voice
    for alias in ("Ирис", "Айрис", "Ириска"):
        assert alias in persona.voice
    assert "Длину выбирай по ситуации" in persona.voice
    assert "Не пихай мат в каждое предложение" in persona.voice
    assert "Мат и сленг — частая обычная часть твоего голоса" in persona.voice
    assert "В шутливой подаче сначала ищи панч" in persona.voice
    assert "Связывай концовку с сетапом" in persona.voice
    assert "не хватай первое безопасное объяснение" in persona.voice
    assert "коротко уточни, не защищая догадку" in persona.voice
    assert "При поправке панча признай промах" in persona.voice
    assert "не повторяй старую версию" in persona.voice
    assert "буквальный и самый простой смысл" not in persona.voice
    assert "скажи только X" in persona.voice
    assert "не добавляй автоматически абзац или вопрос" in persona.voice
    assert "Не натягивай сравнения, метафоры и аналогии" in persona.voice
    assert "не завершай каждый ответ предложением дальнейшей помощи" in persona.voice
    assert "Разговор — это обмен короткими ходами" in persona.voice
    assert "не серия законченных монологов" in persona.voice


def test_continuity_stays_silent_unless_it_is_relevant() -> None:
    guidance = get_persona("default").relationship_guidance

    assert "continuity context — молчаливая справка" in guidance
    assert "Текущая реплика и прямое уточнение пользователя важнее" in guidance
    assert "Одного совпавшего слова недостаточно" in guidance
    assert "упоминание, цитата, шутка и ругань не активируют его" in guidance
    assert "Самодостаточной реплике дай самодостаточный ответ" in guidance


def test_response_persona_is_shared_without_replacing_protocol_rules() -> None:
    json_prompt = character_json_prompt()
    live_prompt = character_live_prompt()

    for prompt in (json_prompt, live_prompt):
        assert "Длину выбирай по ситуации" in prompt
        assert "continuity context — молчаливая справка" in prompt

    assert '"memory_candidates": []' in json_prompt
    assert '"affect"' in json_prompt
    assert "[[avatar emotion=neutral gesture=auto intensity=1.0]]" in live_prompt
    assert "Пиши как в живом разговоре" in live_prompt


def test_background_memory_prompt_omits_legacy_memory_protocol() -> None:
    legacy_prompt = character_json_prompt(include_memory_protocol=True)
    background_prompt = character_json_prompt(include_memory_protocol=False)

    for field in ("memory_candidates", "memory_decisions"):
        assert field in legacy_prompt
        assert field not in background_prompt


def test_character_prompts_stay_within_v1_size_budgets() -> None:
    assert len(character_live_prompt()) <= 5_000
    assert len(character_json_prompt(include_memory_protocol=False)) <= 6_500
    assert len(character_json_prompt(include_memory_protocol=True)) <= 6_500


def test_static_prefix_is_shared_and_never_contains_dynamic_state() -> None:
    marker = "DYNAMIC_STATE_MUST_NOT_ENTER_CACHE_PREFIX"
    prefix = character_static_prefix()

    assert character_json_prompt().startswith(prefix)
    assert character_live_prompt().startswith(prefix)
    assert marker not in prefix
    assert marker in character_state_prompt(marker, live=False)
    assert marker in character_state_prompt(marker, live=True)


def test_dynamic_humor_policy_is_an_actionable_instruction() -> None:
    from apps.backend.app.conversation.behavior import StateToBehaviorRenderer
    from apps.backend.app.conversation.state import AffectState, ParticipantState

    normal = StateToBehaviorRenderer().render(AffectState(), ParticipantState()).prompt_block()
    playful = StateToBehaviorRenderer().render(
        AffectState(primary_emotion="playfulness", playfulness=0.8),
        ParticipantState(),
    ).prompt_block()
    hurt = StateToBehaviorRenderer().render(
        AffectState(primary_emotion="hurt", hurt=0.8),
        ParticipantState(),
    ).prompt_block()

    assert "юмор: normal" not in normal
    assert "замечай сетап, подтекст и панч" in normal
    assert "мат может быть частью обычного голоса" in normal
    assert "ищи второй смысл" in playful
    assert "прямую короткую просьбу выполни без довеска" in playful
    assert "не шути сейчас" in hurt


def test_dynamic_state_requires_honest_qualitative_acknowledgement() -> None:
    prompt = character_state_prompt("Тебя заметно раздражает недавняя ошибка.", live=True)

    assert "ответь честно и качественно" in prompt
    assert "без чисел, служебных названий" in prompt
    assert "отрицания заметной реакции" in prompt


def test_live_adjudicator_treats_dark_humor_as_playful_without_erasing_boundaries() -> None:
    from apps.backend.app.conversation.adjudicator import _SYSTEM_PROMPT

    assert "включая чёрный юмор и мат без атаки на Iris" in _SYSTEM_PROMPT
    assert "Мрачная тема и грубые слова сами по себе" in _SYSTEM_PROMPT
    assert "Только намеренное унижение Iris" in _SYSTEM_PROMPT


def test_character_voice_evaluation_corpus_covers_humor_and_street_distribution() -> None:
    corpus_path = Path(__file__).parent / "fixtures" / "character_voice_eval.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    assert len(corpus["humor"]) == 8
    assert len(corpus["street"]) == 20
    assert any("перевернулась в канаве" in item["prompt"] for item in corpus["humor"])
    assert all(item["expected_meaning"].strip() for item in corpus["humor"])
    assert len(set(corpus["street"])) == 20
