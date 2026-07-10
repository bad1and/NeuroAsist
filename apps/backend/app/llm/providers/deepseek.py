import logging

from openai import APIStatusError, AsyncOpenAI, OpenAIError

from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import (
    ChatMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
)

logger = logging.getLogger(__name__)


class DeepSeekProvider(LLMProvider):
    def __init__(self, settings: Settings, model: str | None = None) -> None:
        self._api_key = settings.llm_api_key
        self._model = model or settings.deepseek_model
        self._client: AsyncOpenAI | None = None

        if self._api_key:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=settings.deepseek_base_url,
            )

    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        if self._client is None:
            raise ValueError("DeepSeek API key is not configured")

        logger.debug(
            "Sending LLM request: provider=deepseek model=%s messages_count=%s",
            self._model,
            len(messages),
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[message.model_dump() for message in messages],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
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

        if not content:
            logger.error("DeepSeek API returned an empty response: model=%s", self._model)
            raise LLMProviderError("DeepSeek API returned an empty response")

        logger.debug("Received LLM response: provider=deepseek model=%s", model)
        return LLMResponse(content=content, model=model)
