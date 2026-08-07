import asyncio
import contextlib
import io
import logging
import re
import time
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.agents.character.protocol import metadata_frame
from apps.backend.app.voice.providers import (
    TTSProvider,
    TTSRequest,
    _minimum_tts_duration_seconds,
)
from apps.backend.app.voice.text import TextChunker, TextNormalizer
from apps.backend.app.voice.directives import (
    AvatarDirective, LiveDirectiveParser, clean_live_reply, make_live_directive_expressive,
)
from apps.backend.app.voice.delivery import (
    LiveVoiceDirectiveParser,
    MAX_SPEECH_TEMPO,
    MIN_SPEECH_TEMPO,
    SpeechPace,
    SpeechSegment,
    VoiceDirective,
    coerce_speech_pace,
    make_speech_segment,
)
from apps.backend.app.voice.style import VoiceStyle, coerce_voice_style, resolve_voice_style

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from apps.backend.app.conversation.behavior import BehaviorGuide
TextCompletedHandler = Callable[[str, str, int, str], Awaitable[None]]
AssistantTerminalHandler = Callable[[str], Awaitable[None]]


@dataclass
class VoiceConnection:
    websocket: WebSocket
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def json(self, payload: dict[str, Any]) -> None:
        async with self.lock:
            await self.websocket.send_json(payload)

    async def segment(self, started: dict[str, Any], audio: bytes, finished: dict[str, Any]) -> None:
        async with self.lock:
            await self.websocket.send_json(started)
            await self.websocket.send_bytes(audio)
            await self.websocket.send_json(finished)


@dataclass
class UtteranceContext:
    session_id: str
    utterance_id: str
    generation: int = 0
    task: asyncio.Task | None = None
    cancelled: bool = False
    audio_started: bool = False
    text_completed: bool = False
    voice_style: VoiceStyle = VoiceStyle.AUTO
    base_pace: SpeechPace = SpeechPace.NORMAL
    playback_rate: float = 1.0
    started_at: float = field(default_factory=time.perf_counter)


@dataclass
class TTSJob:
    index: int
    segment: SpeechSegment
    queue: asyncio.Queue
    task: asyncio.Task


class VoiceSessionManager:
    _FINAL_PUNCTUATION_RE = re.compile(r"[.!?…]$")
    _SOFT_PAUSE_RE = re.compile(r"\s*[,;:—–-]+\s*")
    _SPACE_RE = re.compile(r"\s+")

    def __init__(
        self,
        tts_provider: TTSProvider,
        queue_size: int = 3,
        tts_timeout: float = 20,
        retry_count: int = 0,
        idle_flush_ms: int = 500,
        first_idle_flush_ms: int | None = None,
        next_idle_flush_ms: int | None = None,
        first_segment_chars: int = 40,
        next_segment_chars: int = 75,
        max_segment_chars: int = 110,
        max_segment_words: int = 18,
        safe_segment_words: int | None = None,
        tts_concurrency_mode: str = "1",
        tts_concurrency_min: int = 1,
        tts_concurrency_max: int = 2,
        avatar_service=None,
        event_publisher=None,
    ) -> None:
        self._tts_provider = tts_provider
        self._queue_size = queue_size
        self._tts_timeout = tts_timeout
        self._retry_count = retry_count
        self._first_idle_flush_seconds = (
            first_idle_flush_ms if first_idle_flush_ms is not None else idle_flush_ms
        ) / 1000
        self._next_idle_flush_seconds = (
            next_idle_flush_ms if next_idle_flush_ms is not None else idle_flush_ms
        ) / 1000
        self._chunker_options = {
            "first_target": first_segment_chars,
            "next_target": next_segment_chars,
            "max_chars": max_segment_chars,
            "max_words": max_segment_words,
        }
        self._safe_segment_words = safe_segment_words if safe_segment_words and safe_segment_words > 0 else None
        self._tts_concurrency = self._resolve_tts_concurrency(
            tts_concurrency_mode,
            tts_concurrency_min,
            tts_concurrency_max,
        )
        self._tts_semaphore = asyncio.Semaphore(self._tts_concurrency)
        self._connections: dict[str, VoiceConnection] = {}
        self._active: dict[str, UtteranceContext] = {}
        self._avatar_service = avatar_service
        self._event_publisher = event_publisher
        self._text_completed_handler: TextCompletedHandler | None = None

    def bind_avatar_service(self, avatar_service) -> None:
        self._avatar_service = avatar_service

    def bind_text_completed_handler(
        self,
        handler: TextCompletedHandler | None,
    ) -> None:
        self._text_completed_handler = handler

    async def register(self, session_id: str, websocket: WebSocket) -> VoiceConnection:
        previous = self._connections.get(session_id)
        if previous is not None:
            with contextlib.suppress(Exception):
                await previous.websocket.close(code=1000)
        connection = VoiceConnection(websocket)
        self._connections[session_id] = connection
        return connection

    async def unregister(self, session_id: str, connection: VoiceConnection) -> None:
        if self._connections.get(session_id) is connection:
            self._connections.pop(session_id, None)
            await self.cancel(session_id, notify=False)

    def connected(self, session_id: str) -> bool:
        return session_id in self._connections

    async def start(
        self,
        *,
        session_id: str,
        utterance_id: str,
        transcript: str,
        language: str,
        voice: str,
        agent: CharacterAgent,
        input_mode: str = "voice",
        style_override: str | VoiceStyle = VoiceStyle.AUTO,
        generation: int = 0,
        source_message=None,
        state_context: str | None = None,
        presentation_cue: "BehaviorGuide | None" = None,
        persist_reply: bool | None = None,
        on_assistant_completed: AssistantTerminalHandler | None = None,
        on_assistant_interrupted: AssistantTerminalHandler | None = None,
        raw_transcript: str | None = None,
        transcript_corrections: tuple[dict[str, object], ...] = (),
        playback_rate: float = 1.0,
    ) -> asyncio.Task[None]:
        if not self.connected(session_id):
            raise RuntimeError("Voice WebSocket is not connected")
        await self.cancel(session_id)
        context = UtteranceContext(
            session_id,
            utterance_id,
            generation=generation,
            voice_style=coerce_voice_style(style_override),
            base_pace=self._pace_for_style(style_override),
            playback_rate=max(MIN_SPEECH_TEMPO, min(MAX_SPEECH_TEMPO, float(playback_rate))),
        )
        self._active[session_id] = context
        context.task = asyncio.create_task(
            self._run(
                context, transcript, language, voice, agent, input_mode, source_message, state_context, presentation_cue,
                persist_reply, on_assistant_completed, on_assistant_interrupted,
                raw_transcript, transcript_corrections,
            ),
            name=f"voice-{utterance_id}",
        )
        return context.task

    async def cancel(self, session_id: str, utterance_id: str | None = None, notify: bool = True) -> None:
        context = self._active.get(session_id)
        if context is None or (utterance_id and context.utterance_id != utterance_id):
            return
        context.cancelled = True
        if notify:
            await self._send(context, "voice.utterance.cancelled")
            if self._avatar_service is not None:
                await self._avatar_service.stop(
                    session_id=session_id, utterance_id=context.utterance_id
                )
        if context.task and context.task is not asyncio.current_task():
            context.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await context.task
        if self._active.get(session_id) is context:
            self._active.pop(session_id, None)

    async def _run(
        self,
        context: UtteranceContext,
        transcript: str,
        language: str,
        voice: str,
        agent: CharacterAgent,
        input_mode: str,
        source_message,
        state_context: str | None,
        presentation_cue: "BehaviorGuide | None",
        persist_reply: bool | None,
        on_assistant_completed: AssistantTerminalHandler | None,
        on_assistant_interrupted: AssistantTerminalHandler | None,
        raw_transcript: str | None,
        transcript_corrections: tuple[dict[str, object], ...],
    ) -> None:
        started = time.perf_counter()
        queue: asyncio.Queue[SpeechSegment | None] = asyncio.Queue(self._queue_size)
        worker = asyncio.create_task(self._tts_worker(context, queue, language, voice))
        reply_parts: list[str] = []
        chunker = TextChunker(**self._chunker_options)
        normalizer = TextNormalizer()
        pending: asyncio.Task | None = None
        first_delta_seen = False
        directive_parser = LiveDirectiveParser()
        voice_directive_parser = LiveVoiceDirectiveParser()
        directive_sent = False
        pending_voice_directive: VoiceDirective | None = None
        speech_sequence = 0

        async def apply_directive(directive: AvatarDirective) -> None:
            nonlocal directive_sent
            if directive_sent:
                return
            directive_sent = True
            if presentation_cue is not None and presentation_cue.expression_strength != "muted":
                from apps.backend.app.schemas.character import Emotion
                directive = AvatarDirective(
                    emotion=Emotion(presentation_cue.avatar_emotion),
                    gesture=presentation_cue.allowed_gestures[0],
                    intensity=presentation_cue.avatar_intensity,
                )
            directive = make_live_directive_expressive(directive, transcript)
            context.voice_style = resolve_voice_style(
                context.voice_style,
                emotion=directive.emotion.value,
                pace=presentation_cue.tts_pace if presentation_cue is not None else None,
                emphasis=presentation_cue.tts_emphasis if presentation_cue is not None else 0.0,
            )
            if presentation_cue is not None:
                context.base_pace = coerce_speech_pace(presentation_cue.tts_pace)
            frame = metadata_frame(
                intent=intent,
                emotion=directive.emotion.value,
                gesture=directive.gesture,
                intensity=directive.intensity,
            )
            if self._avatar_service is not None:
                if not self._is_active(context):
                    raise asyncio.CancelledError
                await self._avatar_service.stream_metadata(
                    session_id=context.session_id,
                    utterance_id=context.utterance_id,
                    emotion=directive.emotion,
                    gesture=directive.gesture,
                    gesture_intensity=directive.intensity,
                )
                if not self._is_active(context):
                    await self._avatar_service.stop(
                        session_id=context.session_id,
                        utterance_id=context.utterance_id,
                    )
                    raise asyncio.CancelledError
            await self._send(
                context,
                "voice.metadata",
                metadata=frame,
                emotion=directive.emotion,
                gesture=directive.gesture,
                gesture_intensity=directive.intensity,
                intent=intent,
            )

        async def enqueue_spoken_segment(raw_segment: str) -> None:
            nonlocal pending_voice_directive, speech_sequence
            segment_text = normalizer.normalize(raw_segment)
            if not segment_text:
                return
            segment = make_speech_segment(
                segment_text,
                sequence=speech_sequence,
                base_pace=context.base_pace,
                directive=pending_voice_directive,
                forced_clause_split=segment_text.rstrip().endswith((",", ";", ":")),
            )
            paragraph_pause = 180 if "\n\n" in raw_segment else segment.pause_after_ms
            segment = SpeechSegment(
                text=segment.text,
                pace=segment.pace,
                tempo=max(MIN_SPEECH_TEMPO, min(MAX_SPEECH_TEMPO, segment.tempo * context.playback_rate)),
                emphasis=segment.emphasis,
                pause_before_ms=segment.pause_before_ms,
                pause_after_ms=paragraph_pause,
                sequence=segment.sequence,
            )
            if speech_sequence == 0:
                self._publish_latency(
                    context,
                    "voice.first_speakable_segment",
                    first_speakable_segment_ms=int(
                        (time.perf_counter() - context.started_at) * 1000
                    ),
                    text_length=len(segment.text),
                )
            pending_voice_directive = None
            speech_sequence += 1
            await self._enqueue_tts_segment(queue, worker, segment)

        async def consume_spoken(parts: list[str]) -> None:
            nonlocal pending_voice_directive
            for spoken in parts:
                if not spoken:
                    continue
                for item in voice_directive_parser.feed(spoken):
                    if isinstance(item, VoiceDirective):
                        if chunker.has_pending_text:
                            for raw_segment in chunker.flush():
                                await enqueue_spoken_segment(raw_segment)
                        pending_voice_directive = item
                        continue
                    reply_parts.append(item)
                    await self._send(context, "voice.text.delta", delta=item)
                    for raw_segment in chunker.feed(item):
                        await enqueue_spoken_segment(raw_segment)

        try:
            await self._send(context, "voice.utterance.started")
            intent = agent.classify_intent(transcript)
            if self._avatar_service is not None:
                if not self._is_active(context):
                    raise asyncio.CancelledError
                await self._avatar_service.stream_start(
                    session_id=context.session_id,
                    utterance_id=context.utterance_id,
                    intent=intent,
                )
            iterator = agent.stream_user_message(
                context.session_id,
                transcript,
                stored_reply_transform=clean_live_reply,
                input_mode=input_mode,
                source_message=source_message,
                state_context=state_context,
                schedule_memory=source_message is None,
                persist_reply=persist_reply,
                raw_user_text=raw_transcript,
                voice_corrections=transcript_corrections,
            ).__aiter__()
            pending = asyncio.create_task(anext(iterator))
            while True:
                idle_timeout = (
                    self._next_idle_flush_seconds
                    if chunker.emitted
                    else self._first_idle_flush_seconds
                )
                done, _ = await asyncio.wait({pending}, timeout=idle_timeout)
                if not done:
                    for raw_segment in chunker.flush_idle():
                        await enqueue_spoken_segment(raw_segment)
                    continue
                try:
                    delta = pending.result()
                except StopAsyncIteration:
                    break
                if not first_delta_seen:
                    first_delta_seen = True
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    logger.info(
                        "Live voice first LLM delta: session_id=%s utterance_id=%s llm_first_delta_ms=%s",
                        context.session_id,
                        context.utterance_id,
                        elapsed_ms,
                    )
                    self._publish_latency(context, "voice.llm_first_delta", llm_first_delta_ms=elapsed_ms)
                directive, spoken = directive_parser.feed(delta)
                if directive is not None:
                    await apply_directive(directive)
                await consume_spoken(spoken)
                pending = asyncio.create_task(anext(iterator))
            directive, spoken = directive_parser.finish()
            if directive is not None:
                await apply_directive(directive)
            await consume_spoken(spoken)
            for item in voice_directive_parser.finish():
                if isinstance(item, VoiceDirective):
                    if chunker.has_pending_text:
                        for raw_segment in chunker.flush():
                            await enqueue_spoken_segment(raw_segment)
                    pending_voice_directive = item
                elif item:
                    reply_parts.append(item)
                    await self._send(context, "voice.text.delta", delta=item)
                    for raw_segment in chunker.feed(item):
                        await enqueue_spoken_segment(raw_segment)
            if not directive_sent:
                await apply_directive(AvatarDirective())
            for raw_segment in chunker.flush():
                await enqueue_spoken_segment(raw_segment)
            completed_reply = "".join(reply_parts).strip()
            if on_assistant_completed is not None:
                await on_assistant_completed(completed_reply)
            if self._text_completed_handler is not None and self._is_active(context):
                await self._text_completed_handler(
                    context.session_id,
                    context.utterance_id,
                    context.generation,
                    completed_reply,
                )
            await self._send(
                context,
                "voice.text.completed",
                reply=completed_reply,
                memory_updates=agent.last_memory_updates,
            )
            context.text_completed = True
            await self._enqueue(queue, worker, None)
            await worker
            await self._send(context, "voice.utterance.finished")
            if self._avatar_service is not None and self._is_active(context):
                await self._avatar_service.stream_end(
                    session_id=context.session_id, utterance_id=context.utterance_id
                )
        except asyncio.CancelledError:
            if on_assistant_interrupted is not None:
                await on_assistant_interrupted("".join(reply_parts).strip())
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
            raise
        except Exception as exc:
            if on_assistant_interrupted is not None:
                await on_assistant_interrupted("".join(reply_parts).strip())
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
            tts_failed = worker.done() and not worker.cancelled() and worker.exception() is not None
            code = "provider_unavailable" if context.text_completed or tts_failed else "llm_error"
            await self._send(context, "voice.error", code=code, message=str(exc))
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
            if self._active.get(context.session_id) is context:
                self._active.pop(context.session_id, None)

    async def _tts_worker(self, context: UtteranceContext, queue: asyncio.Queue, language: str, voice: str) -> None:
        segment_id = 0
        next_job_index = 0
        emit_job_index = 0
        input_finished = False
        jobs: dict[int, TTSJob] = {}

        async def fill_jobs(*, block: bool = False) -> None:
            nonlocal input_finished, next_job_index
            while not input_finished and len(jobs) < self._tts_concurrency:
                if block:
                    segment = await queue.get()
                    block = False
                else:
                    try:
                        segment = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                if segment is None:
                    input_finished = True
                    return
                if isinstance(segment, str):
                    segment = make_speech_segment(segment, sequence=next_job_index)
                jobs[next_job_index] = self._create_tts_job(
                    next_job_index, segment, language, voice, context.voice_style
                )
                logger.info(
                    "Live TTS job started: session_id=%s utterance_id=%s job_index=%s "
                    "text_length=%s words=%s queue_depth=%s tts_concurrency=%s",
                    context.session_id,
                    context.utterance_id,
                    next_job_index,
                    len(segment.text),
                    len(segment.text.split()),
                    queue.qsize(),
                    self._tts_concurrency,
                )
                next_job_index += 1

        try:
            await fill_jobs(block=True)
            while jobs:
                await fill_jobs()
                current = jobs[emit_job_index]
                item = await current.queue.get()
                if item is None:
                    await current.task
                    jobs.pop(emit_job_index, None)
                    emit_job_index += 1
                    if not jobs and not input_finished:
                        await fill_jobs(block=True)
                    continue
                if isinstance(item, Exception):
                    raise item
                part, synth_ms = item
                await self._send_tts_part(
                    context,
                    segment_id,
                    part,
                    queue_depth=queue.qsize(),
                    synth_ms=synth_ms,
                )
                context.audio_started = True
                segment_id += 1
        finally:
            for job in jobs.values():
                if not job.task.done():
                    job.task.cancel()
            for job in jobs.values():
                with contextlib.suppress(asyncio.CancelledError):
                    await job.task

    def _create_tts_job(
        self, index: int, segment: SpeechSegment, language: str, voice: str, style: VoiceStyle
    ) -> TTSJob:
        output: asyncio.Queue = asyncio.Queue()

        async def produce() -> None:
            started = time.perf_counter()
            try:
                async for part in self._synthesize_part_stream(segment, language, voice, style=style):
                    synth_ms = int((time.perf_counter() - started) * 1000)
                    await output.put((part, synth_ms))
            except Exception as exc:
                await output.put(exc)
            finally:
                await output.put(None)

        return TTSJob(
            index=index,
            segment=segment,
            queue=output,
            task=asyncio.create_task(produce(), name=f"tts-job-{index}"),
        )

    async def _send_tts_part(
        self,
        context: UtteranceContext,
        segment_id: int,
        part: tuple[SpeechSegment, bytes, str, float, int, int],
        *,
        queue_depth: int,
        synth_ms: int,
    ) -> None:
        connection = self._connections.get(context.session_id)
        active_context = self._active.get(context.session_id)
        if (
            connection is None
            or context.cancelled
            or active_context is not context
        ):
            raise asyncio.CancelledError
        if len(part) == 5:
            part_text, audio, audio_format, duration, attempts = part
            tempo_processing_ms = 0
        else:
            part_text, audio, audio_format, duration, attempts, tempo_processing_ms = part
        if isinstance(part_text, str):
            part_text = make_speech_segment(part_text, sequence=segment_id)
        base = self._event(context, segment_id=segment_id, format=audio_format)
        started = {
            **base,
            "type": "tts.segment.started",
            "text": part_text.text,
            "text_length": len(part_text.text),
            "queue_depth": queue_depth,
            "tts_concurrency": self._tts_concurrency,
            "synth_ms": synth_ms,
            "pace": part_text.pace.value,
            "tempo": part_text.tempo,
            "emphasis": part_text.emphasis.value,
            "pause_after_ms": part_text.pause_after_ms,
            "provider": getattr(
                self._tts_provider,
                "name",
                self._tts_provider.__class__.__name__.removesuffix("Provider").lower(),
            ),
            "tempo_processing_ms": tempo_processing_ms,
        }
        finished = {
            **base,
            "type": "tts.segment.finished",
            "audio_bytes": len(audio),
            "duration_seconds": duration,
            "synth_ms": synth_ms,
        }
        sent_started = time.perf_counter()
        await connection.segment(started, audio, finished)
        websocket_send_ms = int((time.perf_counter() - sent_started) * 1000)
        if self._avatar_service is not None:
            if not self._is_active(context):
                raise asyncio.CancelledError
            await self._avatar_service.stream_segment(
                session_id=context.session_id,
                utterance_id=context.utterance_id,
                sequence=segment_id,
                audio=audio,
                duration_seconds=duration,
                sample_rate=getattr(self._tts_provider, "sample_rate", 24000),
                is_final=False,
            )
            if not self._is_active(context):
                await self._avatar_service.stop(
                    session_id=context.session_id,
                    utterance_id=context.utterance_id,
                )
                raise asyncio.CancelledError
        self._publish_latency(
            context,
            "voice.tts_first_segment_ready" if segment_id == 0 else "voice.tts_segment_ready",
            segment_id=segment_id,
            tts_synthesis_ms=synth_ms,
            tempo_processing_ms=tempo_processing_ms,
            websocket_send_ms=websocket_send_ms,
            pipeline_elapsed_ms=int((time.perf_counter() - context.started_at) * 1000),
        )
        logger.info(
            "Live TTS segment ready: session_id=%s utterance_id=%s segment_id=%s "
            "text_length=%s words=%s audio_bytes=%s duration=%.3f attempts=%s "
            "synth_ms=%s ws_audio_sent_ms=%s queue_depth=%s tts_concurrency=%s",
            context.session_id,
            context.utterance_id,
            segment_id,
            len(part_text.text),
            len(part_text.text.split()),
            len(audio),
            duration,
            attempts,
            synth_ms,
            websocket_send_ms,
            queue_depth,
            self._tts_concurrency,
        )

    async def _synthesize_parts(
        self, segment: SpeechSegment | str, language: str, voice: str, depth: int = 0, style: VoiceStyle = VoiceStyle.AUTO
    ) -> list[tuple[SpeechSegment | str, bytes, str, float, int, int]]:
        legacy_text_result = isinstance(segment, str)
        if legacy_text_result:
            segment = make_speech_segment(segment)
        parts = [
            part async for part in self._synthesize_part_stream(segment, language, voice, depth, style)
        ]
        if legacy_text_result:
            return [(part[0].text, *part[1:]) for part in parts]
        return parts

    async def _synthesize_part_stream(
        self, segment: SpeechSegment | str, language: str, voice: str, depth: int = 0, style: VoiceStyle = VoiceStyle.AUTO
    ):
        if isinstance(segment, str):
            segment = make_speech_segment(segment)
        text = segment.text
        words = text.split()
        request = TTSRequest(
            text=text,
            language=language,
            voice=voice,
            style=style,
            pace=segment.pace,
            tempo=segment.tempo,
            emphasis=segment.emphasis,
            pause_before_ms=segment.pause_before_ms,
            pause_after_ms=segment.pause_after_ms,
        )
        last_error: Exception | None = None
        for attempt in range(1, self._retry_count + 2):
            chunks: list[bytes] = []
            audio_format = "mp3"
            tempo_processing_ms = 0

            async def collect() -> None:
                nonlocal audio_format, tempo_processing_ms
                async for chunk in self._tts_provider.stream(request):
                    if chunk.data:
                        chunks.append(chunk.data)
                        audio_format = chunk.format
                        tempo_processing_ms += int(
                            (chunk.metadata or {}).get("tempo_processing_ms", 0)
                        )

            last_error: Exception | None = None
            try:
                async with self._tts_semaphore:
                    await asyncio.wait_for(collect(), timeout=self._tts_timeout)
                audio = b"".join(chunks)
                duration = await asyncio.to_thread(
                    self._validate_audio, audio, audio_format, text
                )
                yield (
                    segment,
                    audio,
                    audio_format,
                    duration,
                    attempt,
                    tempo_processing_ms,
                )
                return
            except Exception as exc:
                last_error = exc
                if attempt <= self._retry_count:
                    await asyncio.sleep(0.1)

        if len(words) <= 2 or depth >= 4:
            raise RuntimeError("Live TTS could not produce a complete audio segment") from last_error
        logger.warning(
            "Adaptive live TTS split: text_length=%s words=%s depth=%s error_type=%s",
            len(text), len(words), depth, type(last_error).__name__,
        )
        async for part in self._split_and_synthesize(segment, language, voice, depth, style):
            yield part

    async def _split_and_synthesize(
        self, segment: SpeechSegment, language: str, voice: str, depth: int, style: VoiceStyle
    ):
        text = segment.text
        words = self._SOFT_PAUSE_RE.sub(" ", text).split()
        split_at = self._adaptive_split_index(text, words)
        minimum = min(5, max(1, len(words) // 2))
        split_at = max(minimum, min(split_at, len(words) - minimum))
        final_punctuation = text[-1] if self._FINAL_PUNCTUATION_RE.search(text.strip()) else ""
        left = self._cleanup_tts_job_text(
            " ".join(words[:split_at]),
            keep_final_punctuation=False,
        )
        right = " ".join(words[split_at:])
        if final_punctuation and not self._FINAL_PUNCTUATION_RE.search(right):
            right = f"{right}{final_punctuation}"
        right = self._cleanup_tts_job_text(
            right,
            keep_final_punctuation=bool(final_punctuation),
        )
        right_task = asyncio.create_task(
            self._synthesize_parts(
                self._segment_child(segment, right, final=True),
                language,
                voice,
                depth + 1,
                style,
            ),
            name=f"tts-adaptive-right-{depth + 1}",
        )
        try:
            async for part in self._synthesize_part_stream(
                self._segment_child(segment, left, final=False),
                language,
                voice,
                depth + 1,
                style,
            ):
                yield part
        except Exception:
            right_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await right_task
            raise
        for part in await right_task:
            yield part

    def _split_tts_jobs(self, text: str) -> list[str]:
        text = self._SPACE_RE.sub(" ", text).strip()
        if not text:
            return []
        words = text.split()
        if len(words) <= min(self._chunker_options["max_words"], self._safe_segment_words or 18):
            return [self._cleanup_tts_job_text(text, keep_final_punctuation=True)]

        jobs: list[str] = []
        remaining = text
        first = True
        while remaining:
            remaining_words = remaining.split()
            if len(remaining_words) <= 18:
                jobs.append(self._cleanup_tts_job_text(remaining, keep_final_punctuation=True))
                break
            # A seven-word opening is quick, but makes ordinary conversational
            # sentences sound like independently stitched fragments.  Keep a
            # complete thought whenever possible; only use the shorter split
            # after a genuine provider recovery path requires it.
            target = min(14, self._safe_segment_words or 14) if first else (self._safe_segment_words or 18)
            split_at = self._preferred_split_offset(remaining, target_words=target, max_words=18)
            left = self._cleanup_tts_job_text(
                remaining[:split_at],
                keep_final_punctuation=True,
            )
            right = self._cleanup_tts_job_text(
                remaining[split_at:],
                keep_final_punctuation=True,
            )
            if not left or not right:
                break
            jobs.append(left)
            remaining = right
            first = False

        if len(jobs) >= 2 and len(jobs[-1].split()) <= 3:
            candidate = f"{jobs[-2]} {jobs[-1]}"
            if len(candidate.split()) <= 18:
                jobs[-2] = candidate
                jobs.pop()
        return jobs or [text]

    @staticmethod
    def _pace_for_style(style: str | None) -> SpeechPace:
        normalized = coerce_voice_style(style)
        if normalized in {"calm", "thoughtful"}:
            return SpeechPace.SLOW
        if normalized == "energetic":
            return SpeechPace.FAST
        return SpeechPace.NORMAL

    @staticmethod
    def _segment_child(
        parent: SpeechSegment,
        text: str,
        *,
        final: bool,
    ) -> SpeechSegment:
        return SpeechSegment(
            text=text,
            pace=parent.pace,
            tempo=parent.tempo,
            emphasis=parent.emphasis,
            pause_before_ms=0 if final else parent.pause_before_ms,
            pause_after_ms=parent.pause_after_ms if final else 60,
            sequence=parent.sequence,
        )

    def _preferred_split_offset(self, text: str, *, target_words: int, max_words: int) -> int:
        words = text.split()
        min_words = 4
        best: tuple[int, int] | None = None
        patterns = (
            r"[.!?…]\s+",
            r"[;:]\s+",
            r",\s+",
        )
        for priority, pattern in enumerate(patterns):
            for match in re.finditer(pattern, text):
                prefix_words = text[: match.end()].split()
                word_count = len(prefix_words)
                if min_words <= word_count <= max_words:
                    score = priority * 100 + abs(word_count - target_words)
                    if best is None or score < best[0]:
                        best = (score, match.end())
            if best is not None and best[0] < 100:
                return best[1]
        if best is not None:
            return best[1]

        split_words = min(max(target_words, min_words), max_words, len(words) - 1)
        offset = 0
        for index, word in enumerate(words[:split_words]):
            found_at = text.find(word, offset)
            offset = found_at + len(word)
            if index < split_words - 1:
                offset = text.find(" ", offset) + 1
        return offset

    def _adaptive_split_index(self, text: str, words: list[str]) -> int:
        if len(words) <= 2:
            return 1

        midpoint = len(text) // 2
        candidates: list[tuple[int, int]] = []
        for match in re.finditer(r"[,;:—–-]\s+", text):
            prefix_words = self._SOFT_PAUSE_RE.sub(" ", text[: match.end()]).split()
            index = len(prefix_words)
            if 2 <= index <= len(words) - 2:
                candidates.append((abs(match.end() - midpoint), index))
        if candidates:
            return min(candidates)[1]

        if self._safe_segment_words and len(words) <= self._safe_segment_words * 2:
            return min(self._safe_segment_words, len(words) - 1)
        return max(1, len(words) // 2)

    def _cleanup_tts_job_text(self, text: str, *, keep_final_punctuation: bool) -> str:
        text = self._SPACE_RE.sub(" ", text).strip()
        if not text:
            return ""
        if not keep_final_punctuation:
            text = re.sub(r"\s*[,;:—–-]+\s*$", "", text).strip()
        if keep_final_punctuation:
            return text
        if not self._FINAL_PUNCTUATION_RE.search(text):
            text = self._SOFT_PAUSE_RE.sub(" ", text)
            text = self._SPACE_RE.sub(" ", text).strip()
        return text

    def _validate_audio(
        self,
        audio: bytes,
        audio_format: str,
        text: str,
        enforce_min_duration: bool = True,
    ) -> float:
        if not audio:
            raise RuntimeError("TTS provider returned empty audio")
        try:
            import av

            duration = 0.0
            with av.open(io.BytesIO(audio), mode="r") as container:
                for frame in container.decode(audio=0):
                    if frame.sample_rate:
                        duration += frame.samples / frame.sample_rate
        except Exception as exc:
            raise RuntimeError("TTS provider returned undecodable audio") from exc
        if duration <= 0:
            raise RuntimeError("TTS provider returned zero-duration audio")
        if enforce_min_duration and audio_format == "mp3" and duration < _minimum_tts_duration_seconds(text):
            raise RuntimeError("TTS provider returned suspiciously short audio")
        return duration

    @staticmethod
    def _is_tiny_recovery_text(text: str) -> bool:
        return 0 < len(text.split()) <= 2

    async def _enqueue(self, queue: asyncio.Queue, worker: asyncio.Task, job: Any) -> None:
        if worker.done():
            worker.result()
        queued_started = time.perf_counter()
        put = asyncio.create_task(queue.put(job))
        done, _ = await asyncio.wait({put, worker}, return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            put.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await put
            worker.result()
        await put
        if job is not None:
            job_text = job.text if isinstance(job, SpeechSegment) else str(job)
            logger.info(
                "Live TTS chunk queued: text_length=%s words=%s queue_depth=%s chunk_queued_ms=%s",
                len(job_text),
                len(job_text.split()),
                queue.qsize(),
                int((time.perf_counter() - queued_started) * 1000),
            )

    async def _enqueue_tts_segment(
        self,
        queue: asyncio.Queue,
        worker: asyncio.Task,
        segment: SpeechSegment,
    ) -> None:
        jobs = self._split_tts_jobs(segment.text)
        for index, text in enumerate(jobs):
            is_first = index == 0
            is_last = index == len(jobs) - 1
            job = SpeechSegment(
                text=text,
                pace=segment.pace,
                tempo=segment.tempo,
                emphasis=segment.emphasis,
                pause_before_ms=segment.pause_before_ms if is_first else 0,
                pause_after_ms=segment.pause_after_ms if is_last else 60,
                sequence=segment.sequence + index,
            )
            await self._enqueue(queue, worker, job)
        if len(jobs) > 1:
            logger.info(
                "Live TTS safe pre-split queued: source_length=%s source_words=%s jobs=%s safe_words=%s",
                len(segment.text),
                len(segment.text.split()),
                len(jobs),
                self._safe_segment_words,
            )

    async def _enqueue_tts_text(self, queue: asyncio.Queue, worker: asyncio.Task, text: str) -> None:
        """Backward-compatible adapter used by existing tests."""
        await self._enqueue_tts_segment(
            queue,
            worker,
            make_speech_segment(text, sequence=0),
        )

    def _event(self, context: UtteranceContext, **payload: Any) -> dict[str, Any]:
        return {
            "version": 1,
            "session_id": context.session_id,
            "utterance_id": context.utterance_id,
            "generation": context.generation,
            "timestamp_ms": int(time.monotonic() * 1000),
            **payload,
        }

    async def _send(self, context: UtteranceContext, event_type: str, **payload: Any) -> None:
        connection = self._connections.get(context.session_id)
        if connection is None or not self._is_active(context):
            return
        await connection.json({**self._event(context, **payload), "type": event_type})

    def _is_active(self, context: UtteranceContext) -> bool:
        return (
            not context.cancelled
            and self._active.get(context.session_id) is context
        )

    def _publish_latency(self, context: UtteranceContext, event_type: str, **payload: Any) -> None:
        if self._event_publisher is None:
            return
        self._event_publisher(
            event_type,
            "info",
            "Voice latency milestone",
            {"session_id": context.session_id, "utterance_id": context.utterance_id, **payload},
        )

    @staticmethod
    def _resolve_tts_concurrency(mode: str, minimum: int, maximum: int) -> int:
        minimum = max(1, minimum)
        maximum = max(minimum, maximum)
        if mode == "auto":
            return 1
        try:
            return max(minimum, min(min(maximum, 2), int(mode)))
        except ValueError:
            return minimum
