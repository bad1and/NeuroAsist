import asyncio
import logging
import time
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.llm.base import LLMProviderError
from apps.backend.app.llm.providers.deepseek import DeepSeekProvider
from apps.backend.app.schemas.voice import (
    VoiceChatResponse,
    VoiceLiveResponse,
    VoiceProviderStats,
    VoiceTTSStatusResponse,
)
from apps.backend.app.voice.providers import split_tts_chunks

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/voice/chat", response_model=VoiceChatResponse | VoiceLiveResponse)
async def voice_chat(
    request: Request,
    audio: UploadFile = File(...),
    session_id: str = Form(default="default"),
    language: str = Form(default="auto"),
    live: bool = Form(default=False),
) -> VoiceChatResponse | VoiceLiveResponse:
    request_started = time.perf_counter()
    voice_request_id = uuid4().hex
    settings = request.app.state.settings
    history = request.app.state.history
    event_bus = request.app.state.event_bus
    runtime_settings = request.app.state.runtime_settings
    voice_service = request.app.state.voice_service

    selected_language = language if language != "auto" else runtime_settings.voice_language
    if selected_language not in {"auto", "ru", "en"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported voice language",
        )

    upload_save_started = time.perf_counter()
    upload_path = await voice_service.save_upload(audio)
    upload_save_ms = int((time.perf_counter() - upload_save_started) * 1000)
    event_bus.publish(
        "voice.upload_received",
        "info",
        "Voice upload received",
        {
            "session_id": session_id,
            "language": selected_language,
            "duration_ms": upload_save_ms,
        },
    )

    try:
        event_bus.publish(
            "voice.transcribing_started",
            "info",
            "Voice transcription started",
            {"session_id": session_id},
        )
        stt_result = await asyncio.wait_for(
            voice_service.stt_provider.transcribe(upload_path, selected_language),
            timeout=settings.voice_stt_timeout_seconds,
        )
        if not stt_result.text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not transcribe speech",
            )
        event_bus.publish(
            "voice.transcribing_finished",
            "info",
            "Voice transcription finished",
            {
                "session_id": session_id,
                "language": stt_result.language,
                "duration_ms": stt_result.duration_ms,
            },
        )

        provider = DeepSeekProvider(settings)
        agent = CharacterAgent(
            llm_provider=provider,
            history=history,
            history_limit=settings.chat_history_limit,
            event_publisher=event_bus.publish,
        )
        voice = voice_service.resolve_tts_voice(
            stt_result.language,
            runtime_settings.voice_tts_voice,
        )
        if live:
            utterance_id = uuid4().hex
            manager = request.app.state.voice_session_manager
            if not manager.connected(session_id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Voice WebSocket must be connected before live request",
                )
            await manager.start(
                session_id=session_id,
                utterance_id=utterance_id,
                transcript=stt_result.text,
                language=stt_result.language,
                voice=voice,
                agent=agent,
            )
            event_bus.publish(
                "voice.live_started",
                "info",
                "Live voice response started",
                {
                    "session_id": session_id,
                    "utterance_id": utterance_id,
                    "voice_request_id": voice_request_id,
                },
            )
            return VoiceLiveResponse(
                session_id=session_id,
                utterance_id=utterance_id,
                voice_request_id=voice_request_id,
                transcript=stt_result.text,
            )
        event_bus.publish(
            "chat.started",
            "info",
            "Voice chat request started",
            {"session_id": session_id, "message_length": len(stt_result.text)},
        )
        llm_started = time.perf_counter()
        result = await asyncio.wait_for(
            agent.handle_user_message(session_id, stt_result.text),
            timeout=settings.voice_llm_timeout_seconds,
        )
        llm_duration_ms = int((time.perf_counter() - llm_started) * 1000)
        tts_status = "disabled"
        if settings.voice_tts_enabled and result["reply"].strip():
            tts_status = "queued"
            voice_service.set_tts_job(
                voice_request_id,
                {
                    "status": "queued",
                    "audio_url": None,
                    "voice": voice,
                },
            )
            asyncio.create_task(
                _run_tts_background(
                    voice_service=voice_service,
                    event_bus=event_bus,
                    settings=settings,
                    session_id=session_id,
                    voice_request_id=voice_request_id,
                    reply=result["reply"],
                    voice=voice,
                )
            )
        elif not result["reply"].strip():
            tts_status = "skipped"
            voice_service.set_tts_job(
                voice_request_id,
                {
                    "status": "skipped",
                    "audio_url": None,
                    "voice": voice if settings.voice_tts_enabled else None,
                },
            )
        else:
            voice_service.set_tts_job(
                voice_request_id,
                {
                    "status": "disabled",
                    "audio_url": None,
                    "voice": None,
                },
            )

        event_bus.publish(
            "voice.completed",
            "info",
            "Voice chat request completed",
            {
                "session_id": session_id,
                "voice_request_id": voice_request_id,
                "upload_save_ms": upload_save_ms,
                "stt_ms": stt_result.duration_ms,
                "llm_ms": llm_duration_ms,
                "tts_status": tts_status,
                "total_ms": int((time.perf_counter() - request_started) * 1000),
            },
        )
    except HTTPException:
        event_bus.publish(
            "voice.error",
            "error",
            "Voice request failed",
            {"session_id": session_id},
        )
        raise
    except LLMProviderError as exc:
        logger.error("LLM provider failed during voice request", exc_info=True)
        event_bus.publish(
            "voice.error",
            "error",
            "LLM provider failed during voice request",
            {"session_id": session_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except TimeoutError as exc:
        logger.error("Voice request timed out", exc_info=True)
        event_bus.publish(
            "voice.error",
            "error",
            "Voice request timed out",
            {"session_id": session_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Voice request timed out",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected voice request failure")
        event_bus.publish(
            "voice.error",
            "error",
            "Voice request failed",
            {"session_id": session_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal voice error",
        ) from exc
    finally:
        voice_service.cleanup_upload(upload_path)

    return VoiceChatResponse(
        voice_request_id=voice_request_id,
        transcript=stt_result.text,
        reply=result["reply"],
        emotion=result["emotion"],
        intent=result["intent"],
        reply_audio_url=None,
        tts_status=tts_status,
        stt=VoiceProviderStats(
            provider=stt_result.provider,
            model=stt_result.model,
            language=stt_result.language,
            duration_ms=stt_result.duration_ms,
        ),
        tts=VoiceProviderStats(
            provider=settings.voice_tts_provider if settings.voice_tts_enabled else "disabled",
            voice=voice if settings.voice_tts_enabled else None,
            duration_ms=0,
        ),
    )


@router.get("/voice/audio/{audio_id}")
def get_voice_audio(audio_id: str, request: Request) -> FileResponse:
    voice_service = request.app.state.voice_service
    path = voice_service.resolve_audio_path(audio_id)
    media_type = "audio/wav" if path.suffix == ".wav" else "audio/mpeg"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/voice/tts/{voice_request_id}", response_model=VoiceTTSStatusResponse)
def get_voice_tts_status(voice_request_id: str, request: Request) -> VoiceTTSStatusResponse:
    voice_service = request.app.state.voice_service
    job = voice_service.get_tts_job(voice_request_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice TTS job not found",
        )
    return VoiceTTSStatusResponse.model_validate(job)


async def _run_tts_background(
    *,
    voice_service,
    event_bus,
    settings,
    session_id: str,
    voice_request_id: str,
    reply: str,
    voice: str,
) -> None:
    output_path = voice_service.next_tts_path(settings.voice_tts_provider)
    text = reply.strip()[: settings.voice_tts_max_chars]
    event_bus.publish(
        "voice.tts_started",
        "info",
        "Voice synthesis started",
        {
            "session_id": session_id,
            "voice_request_id": voice_request_id,
            "voice": voice,
            "text_length": len(text),
            "chunks_count": len(split_tts_chunks(text)),
        },
    )
    try:
        tts_result = await asyncio.wait_for(
            voice_service.tts_provider.synthesize(text, voice, output_path),
            timeout=settings.voice_tts_background_timeout_seconds,
        )
    except TimeoutError:
        logger.info(
            "Voice synthesis fallback activated: voice_request_id=%s voice=%s error_type=TimeoutError",
            voice_request_id,
            voice,
        )
        voice_service.set_tts_job(
            voice_request_id,
            {
                "status": "failed",
                "audio_url": None,
                "voice": voice,
                "error": "Voice synthesis timed out",
                "error_type": "TimeoutError",
                "recoverable": True,
                "fallback": "browser_speech",
            },
        )
        event_bus.publish(
            "voice.tts_failed",
            "warning",
            "Voice synthesis timed out",
            {
                "session_id": session_id,
                "voice_request_id": voice_request_id,
                "voice": voice,
                "failed_chunk_index": None,
                "error_type": "TimeoutError",
                "recoverable": True,
                "fallback": "browser_speech",
            },
        )
    except Exception as exc:
        logger.info(
            "Voice synthesis fallback activated: voice_request_id=%s voice=%s error_type=%s",
            voice_request_id,
            voice,
            type(exc).__name__,
        )
        logger.debug("Voice synthesis fallback details", exc_info=True)
        voice_service.set_tts_job(
            voice_request_id,
            {
                "status": "failed",
                "audio_url": None,
                "voice": voice,
                "error": "Voice synthesis failed",
                "error_type": type(exc).__name__,
                "recoverable": True,
                "fallback": "browser_speech",
            },
        )
        event_bus.publish(
            "voice.tts_failed",
            "warning",
            "Voice synthesis failed",
            {
                "session_id": session_id,
                "voice_request_id": voice_request_id,
                "voice": voice,
                "failed_chunk_index": None,
                "error_type": type(exc).__name__,
                "recoverable": True,
                "fallback": "browser_speech",
            },
        )
    else:
        audio_url = f"/voice/audio/{tts_result.audio_path.name}"
        voice_service.set_tts_job(
            voice_request_id,
            {
                "status": "ready",
                "audio_url": audio_url,
                "voice": tts_result.voice,
                "duration_ms": tts_result.duration_ms,
                "chunks_count": tts_result.chunks_count,
                "audio_duration_seconds": tts_result.audio_duration_seconds,
            },
        )
        event_bus.publish(
            "voice.tts_ready",
            "info",
            "Voice synthesis ready",
            {
                "session_id": session_id,
                "voice_request_id": voice_request_id,
                "audio_url": audio_url,
                "duration_ms": tts_result.duration_ms,
                "voice": tts_result.voice,
                "chunks_count": tts_result.chunks_count,
                "audio_duration_seconds": tts_result.audio_duration_seconds,
            },
        )


def _default_voice(settings, language: str) -> str:
    return settings.voice_silero_speaker_ru
