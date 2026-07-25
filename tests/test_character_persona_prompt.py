from apps.backend.app.agents.character.persona import get_persona
from apps.backend.app.agents.character.prompts import character_json_prompt, character_live_prompt


def test_default_persona_requires_adaptive_conversational_replies() -> None:
    persona = get_persona("default")

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
