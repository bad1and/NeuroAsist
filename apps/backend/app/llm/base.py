from abc import ABC, abstractmethod

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str


class LLMProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        raise NotImplementedError
