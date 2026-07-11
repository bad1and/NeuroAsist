from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

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

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Yield plain assistant text deltas in provider order."""
        raise NotImplementedError
