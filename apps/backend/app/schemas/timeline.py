from typing import Literal

from pydantic import BaseModel, Field


class TimelineMessageCreate(BaseModel):
    role: Literal["user", "assistant", "system_event"]
    content: str = Field(min_length=1, max_length=8000)
    client_message_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: Literal["pending", "accepted", "streaming", "completed", "cancelled", "interrupted", "failed"] = "completed"
    input_mode: Literal["voice", "text", "system"] = "text"


class TimelineCorrection(BaseModel):
    corrected_content: str = Field(min_length=1, max_length=8000)
