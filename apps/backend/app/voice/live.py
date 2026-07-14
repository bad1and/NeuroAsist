import asyncio
import contextlib
import io
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from apps.backend.app.agents.character.agent import CharacterAgent
from apps.backend.app.voice.providers import (
    TTSProvider,
    TTSRequest,
    _minimum_tts_duration_seconds,
)
from apps.backend.app.voice.text import TextChunker, TextNormalizer
from apps.backend.app.voice.directives import AvatarDirective, LiveDirectiveParser, clean_live_reply

logger = logging.getLogger(__name__)


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
    task: asyncio.Task | None = None
    cancelled: bool = False
    audio_started: bool = False
    text_completed: bool = False
    started_at: float = field(default_factory=time.perf_counter)


@dataclass
class TTSJob:
    index: int
    text: str
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
        self._idle_flush_seconds = idle_flush_ms / 1000
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

    def bind_avatar_service(self, avatar_service) -> None:
        self._avatar_service = avatar_service

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
    ) -> None:
        if not self.connected(session_id):
            raise RuntimeError("Voice WebSocket is not connected")
        await self.cancel(session_id)
        context = UtteranceContext(session_id, utterance_id)
        self._active[session_id] = context
        context.task = asyncio.create_task(
            self._run(context, transcript, language, voice, agent),
            name=f"voice-{utterance_id}",
        )

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

    async def _run(self, context: UtteranceContext, transcript: str, language: str, voice: str, agent: CharacterAgent) -> None:
        started = time.perf_counter()
        queue: asyncio.Queue[str | None] = asyncio.Queue(self._queue_size)
        worker = asyncio.create_task(self._tts_worker(context, queue, language, voice))
        reply_parts: list[str] = []
        chunker = TextChunker(**self._chunker_options)
        normalizer = TextNormalizer()
        pending: asyncio.Task | None = None
        first_delta_seen = False
        directive_parser = LiveDirectiveParser()
        directive_sent = False

        async def apply_directive(directive: AvatarDirective) -> None:
            nonlocal directive_sent
            if directive_sent:
                return
            directive_sent = True
            if self._avatar_service is not None:
                await self._avatar_service.stream_metadata(
                    session_id=context.session_id,
                    utterance_id=context.utterance_id,
                    emotion=directive.emotion,
                    gesture=directive.gesture,
                    gesture_intensity=directive.intensity,
                )
            await self._send(
                context,
                "voice.metadata",
                emotion=directive.emotion,
                gesture=directive.gesture,
                gesture_intensity=directive.intensity,
                intent=intent,
            )

        async def consume_spoken(parts: list[str]) -> None:
            for spoken in parts:
                if not spoken:
                    continue
                reply_parts.append(spoken)
                await self._send(context, "voice.text.delta", delta=spoken)
                for raw_segment in chunker.feed(spoken):
                    segment = normalizer.normalize(raw_segment)
                    if segment:
                        await self._enqueue_tts_text(queue, worker, segment)

        try:
            await self._send(context, "voice.utterance.started")
            intent = agent.classify_intent(transcript)
            if self._avatar_service is not None:
                await self._avatar_service.stream_start(
                    session_id=context.session_id,
                    utterance_id=context.utterance_id,
                    intent=intent,
                )
            iterator = agent.stream_user_message(
                context.session_id, transcript, stored_reply_transform=clean_live_reply
            ).__aiter__()
            pending = asyncio.create_task(anext(iterator))
            while True:
                done, _ = await asyncio.wait({pending}, timeout=self._idle_flush_seconds)
                if not done:
                    for raw_segment in chunker.flush_idle():
                        segment = normalizer.normalize(raw_segment)
                        if segment:
                            await self._enqueue_tts_text(queue, worker, segment)
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
            if not directive_sent:
                await apply_directive(AvatarDirective())
            for raw_segment in chunker.flush():
                segment = normalizer.normalize(raw_segment)
                if segment:
                    await self._enqueue_tts_text(queue, worker, segment)
            await self._send(context, "voice.text.completed", reply="".join(reply_parts).strip())
            context.text_completed = True
            await self._enqueue(queue, worker, None)
            await worker
            await self._send(context, "voice.utterance.finished")
            if self._avatar_service is not None:
                await self._avatar_service.stream_end(
                    session_id=context.session_id, utterance_id=context.utterance_id
                )
        except asyncio.CancelledError:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
            raise
        except Exception as exc:
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
                    text = await queue.get()
                    block = False
                else:
                    try:
                        text = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                if text is None:
                    input_finished = True
                    return
                jobs[next_job_index] = self._create_tts_job(next_job_index, text, language, voice)
                logger.info(
                    "Live TTS job started: session_id=%s utterance_id=%s job_index=%s "
                    "text_length=%s words=%s queue_depth=%s tts_concurrency=%s",
                    context.session_id,
                    context.utterance_id,
                    next_job_index,
                    len(text),
                    len(text.split()),
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

    def _create_tts_job(self, index: int, text: str, language: str, voice: str) -> TTSJob:
        output: asyncio.Queue = asyncio.Queue()

        async def produce() -> None:
            started = time.perf_counter()
            try:
                async for part in self._synthesize_part_stream(text, language, voice):
                    synth_ms = int((time.perf_counter() - started) * 1000)
                    await output.put((part, synth_ms))
            except Exception as exc:
                await output.put(exc)
            finally:
                await output.put(None)

        return TTSJob(
            index=index,
            text=text,
            queue=output,
            task=asyncio.create_task(produce(), name=f"tts-job-{index}"),
        )

    async def _send_tts_part(
        self,
        context: UtteranceContext,
        segment_id: int,
        part: tuple[str, bytes, str, float, int],
        *,
        queue_depth: int,
        synth_ms: int,
    ) -> None:
        part_text, audio, audio_format, duration, attempts = part
        connection = self._connections.get(context.session_id)
        if connection is None or context.cancelled:
            raise asyncio.CancelledError
        base = self._event(context, segment_id=segment_id, format=audio_format)
        started = {
            **base,
            "type": "tts.segment.started",
            "text_length": len(part_text),
            "queue_depth": queue_depth,
            "tts_concurrency": self._tts_concurrency,
            "synth_ms": synth_ms,
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
        if self._avatar_service is not None:
            await self._avatar_service.stream_segment(
                session_id=context.session_id,
                utterance_id=context.utterance_id,
                sequence=segment_id,
                audio=audio,
                duration_seconds=duration,
                sample_rate=getattr(self._tts_provider, "sample_rate", 24000),
                is_final=False,
            )
        self._publish_latency(
            context,
            "voice.tts_first_segment_ready" if segment_id == 0 else "voice.tts_segment_ready",
            segment_id=segment_id,
            tts_synthesis_ms=synth_ms,
            pipeline_elapsed_ms=int((time.perf_counter() - context.started_at) * 1000),
        )
        logger.info(
            "Live TTS segment ready: session_id=%s utterance_id=%s segment_id=%s "
            "text_length=%s words=%s audio_bytes=%s duration=%.3f attempts=%s "
            "synth_ms=%s ws_audio_sent_ms=%s queue_depth=%s tts_concurrency=%s",
            context.session_id,
            context.utterance_id,
            segment_id,
            len(part_text),
            len(part_text.split()),
            len(audio),
            duration,
            attempts,
            synth_ms,
            int((time.perf_counter() - sent_started) * 1000),
            queue_depth,
            self._tts_concurrency,
        )

    async def _synthesize_parts(
        self, text: str, language: str, voice: str, depth: int = 0
    ) -> list[tuple[str, bytes, str, float, int]]:
        return [
            part async for part in self._synthesize_part_stream(text, language, voice, depth)
        ]

    async def _synthesize_part_stream(
        self, text: str, language: str, voice: str, depth: int = 0
    ):
        words = text.split()
        request = TTSRequest(text=text, language=language, voice=voice)
        last_error: Exception | None = None
        for attempt in range(1, self._retry_count + 2):
            chunks: list[bytes] = []
            audio_format = "mp3"

            async def collect() -> None:
                nonlocal audio_format
                async for chunk in self._tts_provider.stream(request):
                    if chunk.data:
                        chunks.append(chunk.data)
                        audio_format = chunk.format

            last_error: Exception | None = None
            try:
                async with self._tts_semaphore:
                    await asyncio.wait_for(collect(), timeout=self._tts_timeout)
                audio = b"".join(chunks)
                duration = await asyncio.to_thread(
                    self._validate_audio, audio, audio_format, text
                )
                yield (text, audio, audio_format, duration, attempt)
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
        async for part in self._split_and_synthesize(text, language, voice, depth):
            yield part

    async def _split_and_synthesize(self, text: str, language: str, voice: str, depth: int):
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
            self._synthesize_parts(right, language, voice, depth + 1),
            name=f"tts-adaptive-right-{depth + 1}",
        )
        try:
            async for part in self._synthesize_part_stream(left, language, voice, depth + 1):
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
            target = 7 if first else (self._safe_segment_words or 10)
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
            logger.info(
                "Live TTS chunk queued: text_length=%s words=%s queue_depth=%s chunk_queued_ms=%s",
                len(job),
                len(job.split()),
                queue.qsize(),
                int((time.perf_counter() - queued_started) * 1000),
            )

    async def _enqueue_tts_text(self, queue: asyncio.Queue, worker: asyncio.Task, text: str) -> None:
        jobs = self._split_tts_jobs(text)
        for job in jobs:
            await self._enqueue(queue, worker, job)
        if len(jobs) > 1:
            logger.info(
                "Live TTS safe pre-split queued: source_length=%s source_words=%s jobs=%s safe_words=%s",
                len(text),
                len(text.split()),
                len(jobs),
                self._safe_segment_words,
            )

    def _event(self, context: UtteranceContext, **payload: Any) -> dict[str, Any]:
        return {
            "version": 1,
            "session_id": context.session_id,
            "utterance_id": context.utterance_id,
            "timestamp_ms": int(time.monotonic() * 1000),
            **payload,
        }

    async def _send(self, context: UtteranceContext, event_type: str, **payload: Any) -> None:
        connection = self._connections.get(context.session_id)
        if connection is None:
            return
        await connection.json({**self._event(context, **payload), "type": event_type})

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
