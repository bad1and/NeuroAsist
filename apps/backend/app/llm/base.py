from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, Field


_llm_call_purpose: ContextVar[str | None] = ContextVar(
    "llm_call_purpose",
    default=None,
)


@contextmanager
def llm_call_purpose(purpose: str) -> Iterator[None]:
    """Tag one semantic LLM call without changing legacy provider signatures."""

    normalized = str(purpose).strip().lower().replace("-", "_")
    if not normalized:
        raise ValueError("purpose must be non-empty")
    token = _llm_call_purpose.set(normalized)
    try:
        yield
    finally:
        _llm_call_purpose.reset(token)


def current_llm_call_purpose() -> str | None:
    return _llm_call_purpose.get()


class ChatMessage(BaseModel):
    role: str
    content: str


class LLMUsage(BaseModel):
    """Provider-reported token usage, including DeepSeek cache/reasoning detail."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    prompt_cache_hit_tokens: int = Field(default=0, ge=0)
    prompt_cache_miss_tokens: int = Field(default=0, ge=0)


class LLMCallMetrics(BaseModel):
    """Metadata retained even for streaming calls and failed requests."""

    purpose: str
    model: str
    usage: LLMUsage | None = None
    finish_reason: str | None = None
    latency_ms: float = Field(ge=0)
    attempts: int = Field(ge=1)
    succeeded: bool


class LLMResponse(BaseModel):
    content: str
    model: str
    usage: LLMUsage | None = None
    finish_reason: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    attempts: int = Field(default=1, ge=1)
    purpose: str | None = None


class LLMProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        raise NotImplementedError

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Yield plain assistant text deltas in provider order."""
        raise NotImplementedError

    async def generate_structured(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Generate schema-bound JSON; providers may override sampling controls."""
        return await self.generate(messages)
