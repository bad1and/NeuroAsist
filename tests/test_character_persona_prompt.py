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
    assert "Ты — Iris" in persona.voice
    for alias in ("Ирис", "Айрис", "Ириска"):
        assert alias in persona.voice
    assert "Длину выбирай по ситуации" in persona.voice
    assert "Не пихай мат в каждое предложение" in persona.voice
    assert "не превращай каждый ответ в шутку" in persona.voice
    assert "Не натягивай сравнения, метафоры и аналогии" in persona.voice
    assert "не завершай каждый ответ предложением дальнейшей помощи" in persona.voice


def test_continuity_stays_silent_unless_it_is_relevant() -> None:
    guidance = get_persona("default").relationship_guidance

    assert "continuity context — молчаливая справка" in guidance
    assert "Не демонстрируй память ради демонстрации" in guidance
    assert "Не превращай случайную деталь из памяти" in guidance
    assert "Если текущая реплика самодостаточна, просто отвечай на неё" in guidance


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
