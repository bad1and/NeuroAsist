from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CharacterLLMResponse(BaseModel):
    reply: str = Field(min_length=1)
    emotion: Literal["neutral", "happy", "annoyed", "smirk", "thinking"]
    intent: Literal["casual_chat", "question", "task_request", "unknown"]
    # Optional to preserve responses produced by the v0.4 prompt/schema.
    gesture: Literal[
        "none", "auto", "talk", "greeting", "agreement", "disagreement", "question",
        "explanation", "thinking", "surprise", "frustration", "farewell", "shrug",
    ] = "auto"

    @field_validator("reply")
    @classmethod
    def reply_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reply must not be blank")
        return stripped
