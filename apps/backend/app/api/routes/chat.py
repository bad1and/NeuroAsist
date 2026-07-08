import logging

from fastapi import APIRouter, HTTPException, Request, status

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import LLMProviderError
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
from apps.backend.app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    settings = request.app.state.settings
    history = request.app.state.history
    provider = DeepSeekProvider(settings)
    agent = CharacterAgent(
        llm_provider=provider,
        history=history,
        history_limit=settings.chat_history_limit,
    )

    try:
        result = await agent.handle_user_message(payload.session_id, payload.message)
    except ValueError as exc:
        logger.error(
            "Chat request failed: session_id=%s message_length=%s",
            payload.session_id,
            len(payload.message),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except LLMProviderError as exc:
        logger.error(
            "LLM provider failed during chat request: session_id=%s message_length=%s",
            payload.session_id,
            len(payload.message),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected /chat failure: session_id=%s message_length=%s",
            payload.session_id,
            len(payload.message),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal chat error",
        ) from exc

    logger.info(
        "Chat request complete: session_id=%s message_length=%s",
        payload.session_id,
        len(payload.message),
    )
    return ChatResponse(**result)
