import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from openai import APIStatusError, AsyncOpenAI, OpenAIError

from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import (
    ChatMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
)

logger = logging.getLogger(__name__)

_ClientKey = tuple[str, str, float, int]

# One HTTP client (and therefore one connection pool) per endpoint per event
# loop. A fresh AsyncOpenAI per utterance pays a new TLS handshake before the
# first token and leaks the pool, because nothing ever closes it. Clients are
# bound to the loop that created their connections, so the loop is part of the
# key: a second loop (tests, a restarted app) gets its own client instead of
# reusing sockets it cannot await on.
_CLIENTS: dict[_ClientKey, tuple[AsyncOpenAI, asyncio.AbstractEventLoop]] = {}


def _shared_client(api_key: str, base_url: str, timeout: float) -> AsyncOpenAI:
    loop = asyncio.get_running_loop()
    for stale_key, (_, stale_loop) in list(_CLIENTS.items()):
        # Nothing can be awaited on a closed loop, so the entry is dropped
        # rather than closed; its sockets died with the loop.
        if stale_loop.is_closed():
            _CLIENTS.pop(stale_key, None)
    key: _ClientKey = (api_key, base_url, timeout, id(loop))
    existing = _CLIENTS.get(key)
    if existing is not None:
        return existing[0]
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=1,
    )
    _CLIENTS[key] = (client, loop)
    return client


async def close_shared_clients() -> None:
    """Close pooled LLM clients owned by the running loop (called on shutdown)."""
    loop = asyncio.get_running_loop()
    for key, (client, owner_loop) in list(_CLIENTS.items()):
        if owner_loop is not loop:
            continue
        _CLIENTS.pop(key, None)
        with contextlib.suppress(Exception):
            await client.close()


class DeepSeekProvider(LLMProvider):
    def __init__(
        self,
        settings: Settings,
        model: str | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        # Optional overrides let specialized agents use a separately scoped
        # credential without changing the main conversational provider.
        self._api_key = api_key if api_key is not None else settings.llm_api_key
        self._model = model or settings.deepseek_model
        self._base_url = base_url or settings.deepseek_base_url
        # An unbounded request keeps the assistant lease open forever when the
        # provider stalls; voice_llm_timeout_seconds finally gets applied here.
        self._timeout = float(timeout if timeout is not None else settings.voice_llm_timeout_seconds)

    @property
    def _client(self) -> AsyncOpenAI | None:
        """Lazily resolved pooled client; None when no API key is configured."""
        if not self._api_key:
            return None
        return _shared_client(self._api_key, self._base_url, self._timeout)

    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        return await self._generate_json(messages, temperature=0.7)

    async def generate_structured(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
    ) -> LLMResponse:
        return await self._generate_json(messages, temperature=temperature)

    async def _generate_json(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
    ) -> LLMResponse:
        client = self._client
        if client is None:
            raise ValueError("DeepSeek API key is not configured")

        logger.debug(
            "Sending LLM request: provider=deepseek model=%s messages_count=%s",
            self._model,
            len(messages),
        )

        for empty_attempt in range(2):
            try:
                response = await client.chat.completions.create(
                    model=self._model,
                    messages=[message.model_dump() for message in messages],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                choice = response.choices[0]
                content = choice.message.content
                model = response.model or self._model
            except APIStatusError as exc:
                logger.error(
                    "DeepSeek API status error: status_code=%s model=%s",
                    exc.status_code,
                    self._model,
                )
                raise LLMProviderError(
                    f"DeepSeek API returned HTTP {exc.status_code}"
                ) from exc
            except (OpenAIError, IndexError, TypeError, ValueError) as exc:
                logger.error(
                    "DeepSeek API request failed: model=%s exception_type=%s",
                    self._model,
                    type(exc).__name__,
                )
                raise LLMProviderError("DeepSeek API request failed") from exc

            if isinstance(content, str) and content.strip():
                logger.debug("Received LLM response: provider=deepseek model=%s", model)
                return LLMResponse(content=content, model=model)

            logger.warning(
                "DeepSeek completion was empty: model=%s attempt=%s finish_reason=%s choices=%s",
                model,
                empty_attempt + 1,
                getattr(choice, "finish_reason", None),
                len(response.choices),
            )

        raise LLMProviderError("DeepSeek API returned an empty response")

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        client = self._client
        if client is None:
            raise ValueError("DeepSeek API key is not configured")
        try:
            response = await client.chat.completions.create(
                model=self._model,
                messages=[message.model_dump() for message in messages],
                temperature=0.7,
                stream=True,
            )
            async for chunk in response:
                try:
                    content = chunk.choices[0].delta.content
                except (IndexError, AttributeError, TypeError):
                    continue
                if content:
                    yield content
        except APIStatusError as exc:
            raise LLMProviderError(
                f"DeepSeek API returned HTTP {exc.status_code}"
            ) from exc
        except OpenAIError as exc:
            raise LLMProviderError("DeepSeek API streaming request failed") from exc
