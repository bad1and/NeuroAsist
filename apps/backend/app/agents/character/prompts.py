from apps.backend.app.agents.character.persona import PersonaConfig, get_persona


def character_json_prompt(persona: PersonaConfig | None = None) -> str:
    persona = persona or get_persona("default")
    return f"""{persona.voice}

{persona.relationship_guidance}

КРИТИЧЕСКИ ВАЖНО: верни только один валидный JSON-объект Character Protocol v3.
Никакого markdown, code fence или пояснений до/после JSON. Поле reply — единственный
видимый пользователю текст. metadata никогда не добавляй в reply.
Схема:
{{
  "protocol_version": 3,
  "reply": "видимый ответ пользователю на русском",
  "intent": "casual_chat|question|task_request|unknown",
  "affect": {{"emotion": "neutral|happy|sad|angry|annoyed|smirk|thinking|surprised|embarrassed|concerned", "intensity": 0.0, "valence": 0.0, "arousal": 0.0}},
  "gesture": {{"name": "none|auto|talk|greeting|agreement|disagreement|question|explanation|thinking|surprise|frustration|farewell|shrug", "intensity": 0.0, "interrupt": true}},
  "delivery": {{"pace": "slow|normal|fast", "emphasis": 0.0}},
  "continuity": {{"referenced_memory_ids": [], "referenced_episode_ids": [], "closes_open_loop_ids": []}}
}}
"""


def character_live_prompt(persona: PersonaConfig | None = None) -> str:
    persona = persona or get_persona("default")
    return f"""{persona.voice}

{persona.relationship_guidance}

Это live-voice режим. Первой строкой ВСЕГДА выдай служебную метку (например,
[[avatar emotion=smirk gesture=shrug intensity=0.7]]):
[[avatar emotion=neutral gesture=auto intensity=1.0]]
emotion: neutral|happy|sad|angry|annoyed|smirk|thinking|surprised|embarrassed|concerned.
gesture: none|auto|talk|greeting|agreement|disagreement|question|explanation|thinking|surprise|frustration|farewell|shrug.
После метки с новой строки напиши только обычный текст реплики. Метка является metadata:
она не будет показана пользователю и не будет озвучена; не возвращай JSON или markdown.
Не пиши скобочные ремарки действий.
"""


CHARACTER_JSON_PROMPT = character_json_prompt()
CHARACTER_LIVE_PROMPT = character_live_prompt()
CHARACTER_SYSTEM_PROMPT = CHARACTER_JSON_PROMPT
CHARACTER_REPAIR_PROMPT = """Исправь ответ ассистентки в один валидный JSON Character Protocol v3.
Сохрани видимый reply, если он есть. Не добавляй markdown или пояснения. Верни affect, gesture,
delivery и continuity по схеме Character Protocol v3; недостающие metadata заполни нейтральными значениями."""
