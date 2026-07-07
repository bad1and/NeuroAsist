from openai import APIStatusError, AsyncOpenAI, OpenAIError

from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import (
    ChatMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
)


class DeepSeekProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.llm_api_key
        self._model = settings.deepseek_model
        self._client: AsyncOpenAI | None = None

        if self._api_key:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=settings.deepseek_base_url,
            )

    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        if self._client is None:
            raise ValueError("DeepSeek API key is not configured")

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
            raise LLMProviderError(
                f"DeepSeek API returned HTTP {exc.status_code}"
            ) from exc
        except (OpenAIError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError("DeepSeek API request failed") from exc

        if not content:
            raise LLMProviderError("DeepSeek API returned an empty response")

        return LLMResponse(content=content, model=model)
