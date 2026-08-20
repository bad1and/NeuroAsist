import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
)

from apps.backend.app.core.config import Settings
from apps.backend.app.llm.base import (
    ChatMessage,
    LLMCallMetrics,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    LLMUsage,
    current_llm_call_purpose,
)
from apps.backend.app.llm.telemetry import llm_telemetry

logger = logging.getLogger(__name__)

_ClientKey = tuple[str, str, float, int]

# One HTTP client (and therefore one connection pool) per endpoint per event
# loop. A fresh AsyncOpenAI per utterance pays a new TLS handshake before the
# first token and leaks the pool, because nothing ever closes it. Clients are
# bound to the loop that created their connections, so the loop is part of the
# key: a second loop (tests, a restarted app) gets its own client instead of
# reusing sockets it cannot await on.
_CLIENTS: dict[_ClientKey, tuple[AsyncOpenAI, asyncio.AbstractEventLoop]] = {}

_MAX_ATTEMPTS = 2
_RETRYABLE_STATUS_CODES = {408, 409, 429}


@dataclass(frozen=True, slots=True)
class _RequestProfile:
    purpose: str
    max_tokens: int
    thinking: str


_PROFILE_SETTINGS: dict[str, tuple[str, int]] = {
    "chat_json": ("llm_chat_json_max_tokens", 900),
    "chat_live": ("llm_chat_live_max_tokens", 500),
    "memory": ("llm_memory_max_tokens", 1_000),
    "reflection": ("llm_reflection_max_tokens", 300),
    "adjudication": ("llm_adjudication_max_tokens", 350),
    "coding": ("llm_coding_max_tokens", 8_192),
    "chat_json_repair": ("llm_chat_json_max_tokens", 900),
    "chat_json_guard_retry": ("llm_chat_json_max_tokens", 900),
    "chat_live_guard_retry": ("llm_chat_live_max_tokens", 500),
    "memory_repair": ("llm_memory_max_tokens", 1_000),
    "reflection_repair": ("llm_reflection_max_tokens", 300),
}


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
        # Retrying is owned by this provider so SDK retries cannot multiply the
        # explicit request/empty-response retry budget below.
        max_retries=0,
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
        purpose: str = "auto",
    ) -> None:
        # Optional overrides let specialized agents use a separately scoped
        # credential without changing the main conversational provider.
        self._api_key = api_key if api_key is not None else settings.llm_api_key
        self._model = model or settings.deepseek_model
        self._base_url = base_url or settings.deepseek_base_url
        # An unbounded request keeps the assistant lease open forever when the
        # provider stalls; voice_llm_timeout_seconds finally gets applied here.
        self._timeout = float(timeout if timeout is not None else settings.voice_llm_timeout_seconds)
        self._settings = settings
        self._purpose = self._normalize_purpose(purpose)
        self._last_response: LLMResponse | None = None
        self._last_call_metrics: LLMCallMetrics | None = None

    @property
    def purpose(self) -> str:
        return self._purpose

    @property
    def last_response(self) -> LLMResponse | None:
        """Most recent completed response, including an assembled stream."""
        return self._last_response

    @property
    def last_call_metrics(self) -> LLMCallMetrics | None:
        """Most recent call metrics; populated for successes and failures."""
        return self._last_call_metrics

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

        profile = self._profile(stream=False)
        started_at = time.perf_counter()
        request_id = uuid4().hex
        input_chars = sum(len(message.content) for message in messages)
        aggregate_usage: LLMUsage | None = None
        last_finish_reason: str | None = None
        self._last_response = None
        self._last_call_metrics = None

        logger.debug(
            "Sending LLM request: provider=deepseek model=%s purpose=%s messages_count=%s max_tokens=%s",
            self._model,
            profile.purpose,
            len(messages),
            profile.max_tokens,
        )

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            attempt_started_at = time.perf_counter()
            attempt_usage: LLMUsage | None = None
            attempt_finish_reason: str | None = None
            try:
                response = await client.chat.completions.create(
                    model=self._model,
                    messages=[message.model_dump() for message in messages],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=profile.max_tokens,
                    extra_body={"thinking": {"type": profile.thinking}},
                )
                attempt_usage = _extract_usage(getattr(response, "usage", None))
                aggregate_usage = _add_usage(aggregate_usage, attempt_usage)
                choice = response.choices[0]
                content = choice.message.content
                model = response.model or self._model
                attempt_finish_reason = _optional_string(
                    getattr(choice, "finish_reason", None)
                )
                last_finish_reason = attempt_finish_reason
            except asyncio.CancelledError as exc:
                self._record_telemetry(
                    request_id=request_id,
                    profile=profile,
                    messages=messages,
                    input_chars=input_chars,
                    streaming=False,
                    usage=attempt_usage,
                    finish_reason=attempt_finish_reason,
                    attempt_started_at=attempt_started_at,
                    status="cancelled",
                    error_type=type(exc).__name__,
                    attempt=attempt,
                )
                self._record_failure(
                    profile=profile,
                    usage=aggregate_usage,
                    finish_reason=last_finish_reason,
                    started_at=started_at,
                    attempts=attempt,
                )
                raise
            except (OpenAIError, IndexError, TypeError, ValueError, AttributeError) as exc:
                self._record_telemetry(
                    request_id=request_id,
                    profile=profile,
                    messages=messages,
                    input_chars=input_chars,
                    streaming=False,
                    usage=attempt_usage,
                    finish_reason=attempt_finish_reason,
                    attempt_started_at=attempt_started_at,
                    status="error",
                    error_type=type(exc).__name__,
                    attempt=attempt,
                )
                if attempt < _MAX_ATTEMPTS and _is_retryable(exc):
                    logger.warning(
                        "Retrying DeepSeek request: model=%s purpose=%s attempt=%s exception_type=%s",
                        self._model,
                        profile.purpose,
                        attempt,
                        type(exc).__name__,
                    )
                    continue
                self._record_failure(
                    profile=profile,
                    usage=aggregate_usage,
                    finish_reason=last_finish_reason,
                    started_at=started_at,
                    attempts=attempt,
                )
                self._raise_provider_error(exc, streaming=False)

            if isinstance(content, str) and content.strip():
                self._record_telemetry(
                    request_id=request_id,
                    profile=profile,
                    messages=messages,
                    input_chars=input_chars,
                    streaming=False,
                    usage=attempt_usage,
                    finish_reason=last_finish_reason,
                    attempt_started_at=attempt_started_at,
                    status="success",
                    error_type=None,
                    attempt=attempt,
                    model=model,
                )
                result = LLMResponse(
                    content=content,
                    model=model,
                    usage=aggregate_usage,
                    finish_reason=last_finish_reason,
                    latency_ms=_latency_ms(started_at),
                    attempts=attempt,
                    purpose=profile.purpose,
                )
                self._record_success(result)
                self._log_success(result)
                return result

            logger.warning(
                "DeepSeek completion was empty: model=%s attempt=%s finish_reason=%s choices=%s",
                model,
                attempt,
                last_finish_reason,
                len(response.choices),
            )
            self._record_telemetry(
                request_id=request_id,
                profile=profile,
                messages=messages,
                input_chars=input_chars,
                streaming=False,
                usage=attempt_usage,
                finish_reason=last_finish_reason,
                attempt_started_at=attempt_started_at,
                status="empty",
                error_type=None,
                attempt=attempt,
                model=model,
            )
            # Empty or malformed provider output is a semantic failure, not a
            # transport failure. Higher layers already own their single repair
            # or deterministic fallback, so repeating the entire request here
            # would multiply one logical turn invisibly.
            self._record_failure(
                profile=profile,
                usage=aggregate_usage,
                finish_reason=last_finish_reason,
                started_at=started_at,
                attempts=attempt,
            )
            # Return the empty completion to the semantic caller. Character,
            # memory, reflection and coding each already own exactly one
            # purpose-aware repair or deterministic fallback. Raising here
            # would bypass those safe fallbacks and turn a billable response
            # into a user-visible 502.
            empty_result = LLMResponse(
                content="",
                model=model,
                usage=aggregate_usage,
                finish_reason=last_finish_reason,
                latency_ms=_latency_ms(started_at),
                attempts=attempt,
                purpose=profile.purpose,
            )
            self._last_response = empty_result
            return empty_result

        raise AssertionError("unreachable")

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        client = self._client
        if client is None:
            raise ValueError("DeepSeek API key is not configured")

        profile = self._profile(stream=True)
        started_at = time.perf_counter()
        request_id = uuid4().hex
        input_chars = sum(len(message.content) for message in messages)
        aggregate_usage: LLMUsage | None = None
        finish_reason: str | None = None
        assembled: list[str] = []
        model = self._model
        self._last_response = None
        self._last_call_metrics = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            attempt_started_at = time.perf_counter()
            attempt_usage: LLMUsage | None = None
            attempt_finish_reason: str | None = None
            emitted_this_attempt = False
            try:
                response = await client.chat.completions.create(
                    model=self._model,
                    messages=[message.model_dump() for message in messages],
                    temperature=0.7,
                    stream=True,
                    stream_options={"include_usage": True},
                    max_tokens=profile.max_tokens,
                    extra_body={"thinking": {"type": profile.thinking}},
                )
                async for chunk in response:
                    model = _optional_string(getattr(chunk, "model", None)) or model
                    # DeepSeek emits an extra final chunk with choices=[] when
                    # include_usage is enabled. Capture it before reading choices.
                    chunk_usage = _extract_usage(getattr(chunk, "usage", None))
                    attempt_usage = _add_usage(attempt_usage, chunk_usage)
                    aggregate_usage = _add_usage(aggregate_usage, chunk_usage)
                    choices = getattr(chunk, "choices", None)
                    if not choices:
                        continue
                    choice = choices[0]
                    chunk_finish_reason = _optional_string(
                        getattr(choice, "finish_reason", None)
                    )
                    if chunk_finish_reason is not None:
                        attempt_finish_reason = chunk_finish_reason
                        finish_reason = chunk_finish_reason
                    content = getattr(getattr(choice, "delta", None), "content", None)
                    if isinstance(content, str) and content:
                        emitted_this_attempt = True
                        assembled.append(content)
                        yield content
            except (asyncio.CancelledError, GeneratorExit) as exc:
                self._record_telemetry(
                    request_id=request_id,
                    profile=profile,
                    messages=messages,
                    input_chars=input_chars,
                    streaming=True,
                    usage=attempt_usage,
                    finish_reason=attempt_finish_reason,
                    attempt_started_at=attempt_started_at,
                    status="cancelled",
                    error_type=type(exc).__name__,
                    attempt=attempt,
                    model=model,
                )
                self._record_failure(
                    profile=profile,
                    usage=aggregate_usage,
                    finish_reason=attempt_finish_reason,
                    started_at=started_at,
                    attempts=attempt,
                )
                raise
            except (OpenAIError, IndexError, TypeError, ValueError, AttributeError) as exc:
                self._record_telemetry(
                    request_id=request_id,
                    profile=profile,
                    messages=messages,
                    input_chars=input_chars,
                    streaming=True,
                    usage=attempt_usage,
                    finish_reason=attempt_finish_reason,
                    attempt_started_at=attempt_started_at,
                    status="error",
                    error_type=type(exc).__name__,
                    attempt=attempt,
                    model=model,
                )
                # Retrying after yielding text would duplicate the visible prefix.
                if (
                    not emitted_this_attempt
                    and attempt < _MAX_ATTEMPTS
                    and _is_retryable(exc)
                ):
                    logger.warning(
                        "Retrying DeepSeek stream: model=%s purpose=%s attempt=%s exception_type=%s",
                        self._model,
                        profile.purpose,
                        attempt,
                        type(exc).__name__,
                    )
                    continue
                self._record_failure(
                    profile=profile,
                    usage=aggregate_usage,
                    finish_reason=attempt_finish_reason,
                    started_at=started_at,
                    attempts=attempt,
                )
                self._raise_provider_error(exc, streaming=True)

            if emitted_this_attempt:
                self._record_telemetry(
                    request_id=request_id,
                    profile=profile,
                    messages=messages,
                    input_chars=input_chars,
                    streaming=True,
                    usage=attempt_usage,
                    finish_reason=finish_reason,
                    attempt_started_at=attempt_started_at,
                    status="success",
                    error_type=None,
                    attempt=attempt,
                    model=model,
                )
                result = LLMResponse(
                    content="".join(assembled),
                    model=model,
                    usage=aggregate_usage,
                    finish_reason=finish_reason,
                    latency_ms=_latency_ms(started_at),
                    attempts=attempt,
                    purpose=profile.purpose,
                )
                self._record_success(result)
                self._log_success(result)
                return

            logger.warning(
                "DeepSeek stream was empty: model=%s purpose=%s attempt=%s finish_reason=%s",
                model,
                profile.purpose,
                attempt,
                finish_reason,
            )
            self._record_telemetry(
                request_id=request_id,
                profile=profile,
                messages=messages,
                input_chars=input_chars,
                streaming=True,
                usage=attempt_usage,
                finish_reason=attempt_finish_reason,
                attempt_started_at=attempt_started_at,
                status="empty",
                error_type=None,
                attempt=attempt,
                model=model,
            )
            self._record_failure(
                profile=profile,
                usage=aggregate_usage,
                finish_reason=finish_reason,
                started_at=started_at,
                attempts=attempt,
            )
            raise LLMProviderError("DeepSeek API returned an empty stream")

        raise AssertionError("unreachable")

    @staticmethod
    def _normalize_purpose(purpose: str) -> str:
        normalized = str(purpose or "auto").strip().lower().replace("-", "_")
        aliases = {
            "chat": "chat_json",
            "live": "chat_live",
            "structured": "chat_json",
            "memory_extraction": "memory",
        }
        return aliases.get(normalized, normalized)

    def _profile(self, *, stream: bool) -> _RequestProfile:
        purpose = current_llm_call_purpose() or self._purpose
        if purpose == "auto":
            purpose = "chat_live" if stream else "chat_json"
        setting_name, default = _PROFILE_SETTINGS.get(
            purpose,
            _PROFILE_SETTINGS["chat_live" if stream else "chat_json"],
        )
        configured = getattr(self._settings, setting_name, default)
        try:
            max_tokens = int(configured)
        except (TypeError, ValueError):
            max_tokens = default
        if max_tokens <= 0:
            max_tokens = default
        return _RequestProfile(
            purpose=purpose,
            max_tokens=max_tokens,
            thinking="enabled" if purpose == "coding" else "disabled",
        )

    def _record_success(self, response: LLMResponse) -> None:
        self._last_response = response
        self._last_call_metrics = LLMCallMetrics(
            purpose=response.purpose or self._purpose,
            model=response.model,
            usage=response.usage,
            finish_reason=response.finish_reason,
            latency_ms=response.latency_ms or 0.0,
            attempts=response.attempts,
            succeeded=True,
        )

    def _record_failure(
        self,
        *,
        profile: _RequestProfile,
        usage: LLMUsage | None,
        finish_reason: str | None,
        started_at: float,
        attempts: int,
    ) -> None:
        self._last_response = None
        self._last_call_metrics = LLMCallMetrics(
            purpose=profile.purpose,
            model=self._model,
            usage=usage,
            finish_reason=finish_reason,
            latency_ms=_latency_ms(started_at),
            attempts=attempts,
            succeeded=False,
        )

    def _record_telemetry(
        self,
        *,
        request_id: str,
        profile: _RequestProfile,
        messages: list[ChatMessage],
        input_chars: int,
        streaming: bool,
        usage: LLMUsage | None,
        finish_reason: str | None,
        attempt_started_at: float,
        status: str,
        error_type: str | None,
        attempt: int,
        model: str | None = None,
    ) -> None:
        measured = usage or LLMUsage()
        try:
            llm_telemetry.record(
                request_id=request_id,
                purpose=profile.purpose,
                model=model or self._model,
                streaming=streaming,
                thinking=profile.thinking == "enabled",
                max_tokens=profile.max_tokens,
                message_count=len(messages),
                input_chars=input_chars,
                usage_available=usage is not None,
                prompt=measured.prompt_tokens,
                completion=measured.completion_tokens,
                total=measured.total_tokens,
                reasoning=measured.reasoning_tokens,
                cache_hit=measured.prompt_cache_hit_tokens,
                cache_miss=measured.prompt_cache_miss_tokens,
                latency=max(time.perf_counter() - attempt_started_at, 0.0),
                finish_reason=finish_reason,
                status=status,
                error_type=error_type,
                logical_attempt=attempt,
            )
        except Exception as exc:  # Telemetry must never fail an LLM request.
            logger.warning(
                "Failed to record LLM telemetry: exception_type=%s",
                type(exc).__name__,
            )

    @staticmethod
    def _raise_provider_error(exc: Exception, *, streaming: bool) -> None:
        if isinstance(exc, APIStatusError):
            raise LLMProviderError(
                f"DeepSeek API returned HTTP {exc.status_code}"
            ) from exc
        detail = " streaming" if streaming else ""
        raise LLMProviderError(f"DeepSeek API{detail} request failed") from exc

    @staticmethod
    def _log_success(response: LLMResponse) -> None:
        usage = response.usage or LLMUsage()
        logger.info(
            "DeepSeek request completed: model=%s purpose=%s finish_reason=%s latency_ms=%.1f "
            "attempts=%s prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s "
            "cache_hit_tokens=%s cache_miss_tokens=%s",
            response.model,
            response.purpose,
            response.finish_reason,
            response.latency_ms or 0.0,
            response.attempts,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.reasoning_tokens,
            usage.prompt_cache_hit_tokens,
            usage.prompt_cache_miss_tokens,
        )


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, APIStatusError):
        status_code = exc.status_code
        return status_code in _RETRYABLE_STATUS_CODES or status_code >= 500
    return isinstance(exc, (APIConnectionError, APITimeoutError))


def _latency_ms(started_at: float) -> float:
    return max((time.perf_counter() - started_at) * 1_000.0, 0.0)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _field(value: object, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    direct = getattr(value, name, None)
    if direct is not None:
        return direct
    model_extra = getattr(value, "model_extra", None)
    if isinstance(model_extra, dict):
        return model_extra.get(name)
    return None


def _token_count(value: object, name: str) -> int:
    raw = _field(value, name)
    try:
        return max(int(raw), 0) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def _extract_usage(value: object) -> LLMUsage | None:
    if value is None:
        return None
    prompt_tokens = _token_count(value, "prompt_tokens")
    completion_tokens = _token_count(value, "completion_tokens")
    total_raw = _field(value, "total_tokens")
    try:
        total_tokens = max(int(total_raw), 0) if total_raw is not None else 0
    except (TypeError, ValueError):
        total_tokens = 0
    if total_raw is None:
        total_tokens = prompt_tokens + completion_tokens

    reasoning_raw = _field(value, "reasoning_tokens")
    if reasoning_raw is None:
        reasoning_raw = _field(_field(value, "completion_tokens_details"), "reasoning_tokens")
    try:
        reasoning_tokens = max(int(reasoning_raw), 0) if reasoning_raw is not None else 0
    except (TypeError, ValueError):
        reasoning_tokens = 0

    return LLMUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
        prompt_cache_hit_tokens=_token_count(value, "prompt_cache_hit_tokens"),
        prompt_cache_miss_tokens=_token_count(value, "prompt_cache_miss_tokens"),
    )


def _add_usage(current: LLMUsage | None, addition: LLMUsage | None) -> LLMUsage | None:
    if addition is None:
        return current
    if current is None:
        return addition
    return LLMUsage(
        prompt_tokens=current.prompt_tokens + addition.prompt_tokens,
        completion_tokens=current.completion_tokens + addition.completion_tokens,
        total_tokens=current.total_tokens + addition.total_tokens,
        reasoning_tokens=current.reasoning_tokens + addition.reasoning_tokens,
        prompt_cache_hit_tokens=(
            current.prompt_cache_hit_tokens + addition.prompt_cache_hit_tokens
        ),
        prompt_cache_miss_tokens=(
            current.prompt_cache_miss_tokens + addition.prompt_cache_miss_tokens
        ),
    )
