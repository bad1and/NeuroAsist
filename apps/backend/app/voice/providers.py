import asyncio
import contextlib
import json
import re
import shutil
import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class STTResult:
    text: str
    language: str
    duration_ms: int
    provider: str
    model: str | None = None


@dataclass(frozen=True)
class TTSResult:
    audio_path: Path
    duration_ms: int
    provider: str
    voice: str
    chunks_count: int = 1
    audio_duration_seconds: float | None = None


class STTProvider:
    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        raise NotImplementedError

    async def preload(self) -> None:
        return None


class TTSProvider:
    async def synthesize(self, text: str, voice: str, output_path: Path) -> TTSResult:
        raise NotImplementedError


class MockSTTProvider(STTProvider):
    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        return STTResult(
            text="Тестовое голосовое сообщение",
            language="ru" if language == "auto" else language,
            duration_ms=0,
            provider="mock",
            model="mock",
        )


class MockTTSProvider(TTSProvider):
    async def synthesize(self, text: str, voice: str, output_path: Path) -> TTSResult:
        started = time.perf_counter()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 1600)
        return TTSResult(
            audio_path=output_path,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="mock",
            voice=voice,
            audio_duration_seconds=0.1,
        )


class FasterWhisperSTTProvider(STTProvider):
    _RUSSIAN_PROMPT = (
        "Это живой разговор на русском языке. Распознавай речь дословно, "
        "сохраняй смысл, не переводи и не выдумывай слова."
    )

    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._model = None

    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language, started)

    async def preload(self) -> None:
        await asyncio.to_thread(self._ensure_model)

    def _ensure_model(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed") from exc

        if self._model is None:
            self._model = WhisperModel(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    def _transcribe_sync(self, audio_path: Path, language: str, started: float) -> STTResult:
        model = self._ensure_model()
        selected_language = None if language == "auto" else language
        segments, info = model.transcribe(
            str(audio_path),
            language=selected_language,
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 250,
            },
            initial_prompt=self._initial_prompt(selected_language),
            no_speech_threshold=0.45,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        detected_language = getattr(info, "language", None) or selected_language or "auto"
        return STTResult(
            text=text,
            language=detected_language,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="faster_whisper",
            model=self._model_name,
        )

    def _initial_prompt(self, language: str | None) -> str | None:
        if language == "ru":
            return self._RUSSIAN_PROMPT
        return None


class EdgeTTSProvider(TTSProvider):
    _STREAM_IDLE_TIMEOUT_SECONDS = 4
    _POST_AUDIO_IDLE_TIMEOUT_SECONDS = 0.5
    _MAX_CHUNK_CHARS = 90
    _MAX_CHUNK_WORDS = 18
    _CHUNK_RETRIES = 2
    _CHUNK_PAUSE_SECONDS = 0.15
    _RATE = "+20%"
    _VOICE_FALLBACKS = {
        "ru-RU-SvetlanaNeural": [
            "en-US-EmmaMultilingualNeural",
            "en-US-AvaMultilingualNeural",
        ],
        "ru-RU-DmitryNeural": [
            "en-US-AndrewMultilingualNeural",
            "en-US-BrianMultilingualNeural",
        ],
    }

    async def synthesize(self, text: str, voice: str, output_path: Path) -> TTSResult:
        started = time.perf_counter()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts is not installed") from exc

        chunks = self._prepare_chunks(text)
        chunk_paths: list[Path] = []
        chunk_durations: list[float | None] = []
        final_temp_path = output_path.with_name(
            f"{output_path.stem}.tmp{output_path.suffix}"
        )
        final_temp_path.unlink(missing_ok=True)
        selected_voice = voice
        try:
            for index, chunk in enumerate(chunks):
                chunk_path = output_path.with_name(
                    f"{output_path.stem}.part{index:03d}{output_path.suffix}"
                )
                tts_chunk = _prepare_edge_tts_chunk(chunk)
                chunk_duration, selected_voice = await self._synthesize_chunk(
                    edge_tts,
                    tts_chunk,
                    voice,
                    chunk_path,
                )
                chunk_paths.append(chunk_path)
                chunk_durations.append(chunk_duration)

            if len(chunk_paths) == 1:
                chunk_paths[0].replace(final_temp_path)
                chunk_paths = []
            else:
                await asyncio.to_thread(self._concat_mp3_chunks, chunk_paths, final_temp_path)

            audio_duration_seconds = await asyncio.to_thread(
                self._validate_audio_path,
                final_temp_path,
                "edge-tts returned invalid audio",
            )
            self._validate_concatenated_duration(audio_duration_seconds, chunk_durations)
            final_temp_path.replace(output_path)
        finally:
            for chunk_path in chunk_paths:
                chunk_path.unlink(missing_ok=True)
            final_temp_path.unlink(missing_ok=True)

        return TTSResult(
            audio_path=output_path,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="edge_tts",
            voice=selected_voice,
            chunks_count=len(chunks),
            audio_duration_seconds=audio_duration_seconds,
        )

    def _prepare_chunks(self, text: str) -> list[str]:
        chunks = split_tts_chunks(
            text,
            max_chars=self._MAX_CHUNK_CHARS,
            max_words=self._MAX_CHUNK_WORDS,
        )
        if len(chunks) > 1 and shutil.which("ffmpeg") is None:
            return [text]
        return chunks

    async def _synthesize_chunk(
        self,
        edge_tts,
        text: str,
        voice: str,
        output_path: Path,
    ) -> tuple[float | None, str]:
        last_error: Exception | None = None
        for candidate_voice in self._candidate_voices(voice):
            for _ in range(self._CHUNK_RETRIES + 1):
                output_path.unlink(missing_ok=True)
                try:
                    audio_bytes, _stream_completed = await self._write_stream_to_file(
                        edge_tts,
                        text,
                        candidate_voice,
                        output_path,
                    )
                    audio_duration_seconds = await asyncio.to_thread(
                        self._validate_chunk_audio_path,
                        output_path,
                        text,
                        "edge-tts returned invalid audio for chunk",
                    )
                except Exception as exc:
                    last_error = exc
                    output_path.unlink(missing_ok=True)
                    continue

                if audio_bytes > 0:
                    return audio_duration_seconds, candidate_voice

        output_path.unlink(missing_ok=True)
        raise RuntimeError("edge-tts returned no audio for chunk") from last_error

    def _candidate_voices(self, voice: str) -> list[str]:
        return [voice, *self._VOICE_FALLBACKS.get(voice, [])]

    async def _write_stream_to_file(
        self,
        edge_tts,
        text: str,
        voice: str,
        output_path: Path,
    ) -> tuple[int, bool]:
        communicate = edge_tts.Communicate(text, voice, rate=self._RATE)
        audio_bytes = 0
        stream_completed = False
        stream = communicate.stream()
        try:
            with output_path.open("wb") as output:
                while True:
                    try:
                        message = await asyncio.wait_for(
                            anext(stream),
                            timeout=(
                                self._POST_AUDIO_IDLE_TIMEOUT_SECONDS
                                if audio_bytes > 0
                                else self._STREAM_IDLE_TIMEOUT_SECONDS
                            ),
                        )
                    except StopAsyncIteration:
                        stream_completed = True
                        break
                    except TimeoutError:
                        # Some Edge endpoints deliver a complete MP3 and then leave the
                        # websocket open instead of ending the async iterator.  The
                        # audio validator below is the reliable completeness check;
                        # treating the missing EOF as a hard failure discarded valid
                        # audio and multiplied the delay through every retry/fallback.
                        if audio_bytes > 0:
                            break
                        raise

                    if message.get("type") != "audio":
                        continue
                    data = message.get("data", b"")
                    if data:
                        output.write(data)
                        audio_bytes += len(data)
        finally:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(stream.aclose(), timeout=1.0)

        return audio_bytes, stream_completed

    def _validate_audio_path(self, audio_path: Path, error_message: str) -> float | None:
        if audio_path.stat().st_size <= 0:
            raise RuntimeError(error_message)
        audio_duration_seconds = self._probe_duration(audio_path)
        if audio_duration_seconds is not None and audio_duration_seconds <= 0:
            raise RuntimeError(error_message)
        return audio_duration_seconds

    def _validate_chunk_audio_path(
        self,
        audio_path: Path,
        text: str,
        error_message: str,
    ) -> float | None:
        audio_duration_seconds = self._validate_audio_path(audio_path, error_message)
        if audio_duration_seconds is None:
            return None
        minimum_duration_seconds = _minimum_tts_duration_seconds(text)
        if audio_duration_seconds < minimum_duration_seconds:
            raise RuntimeError(
                f"{error_message}: audio duration {audio_duration_seconds:.2f}s "
                f"is shorter than expected {minimum_duration_seconds:.2f}s"
            )
        return audio_duration_seconds

    def _validate_concatenated_duration(
        self,
        audio_duration_seconds: float | None,
        chunk_durations: list[float | None],
    ) -> None:
        if audio_duration_seconds is None or any(duration is None for duration in chunk_durations):
            return
        expected_duration_seconds = sum(duration for duration in chunk_durations if duration is not None)
        if expected_duration_seconds <= 0:
            return
        if audio_duration_seconds < expected_duration_seconds * 0.85:
            raise RuntimeError(
                "edge-tts returned incomplete concatenated audio: "
                f"final duration {audio_duration_seconds:.2f}s, "
                f"chunks duration {expected_duration_seconds:.2f}s"
            )

    def _concat_mp3_chunks(self, chunk_paths: list[Path], output_path: Path) -> None:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg is required to concatenate TTS chunks")

        silence_path = output_path.with_suffix(".silence.mp3")
        try:
            self._write_silence_chunk(silence_path)
            concat_paths: list[Path] = []
            for index, chunk_path in enumerate(chunk_paths):
                concat_paths.append(chunk_path)
                if index < len(chunk_paths) - 1:
                    concat_paths.append(silence_path)

            inputs: list[str] = []
            filter_inputs: list[str] = []
            for index, chunk_path in enumerate(concat_paths):
                inputs.extend(["-i", str(chunk_path)])
                filter_inputs.append(f"[{index}:a]")
            filter_complex = (
                "".join(filter_inputs)
                + f"concat=n={len(concat_paths)}:v=0:a=1[a]"
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    *inputs,
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "[a]",
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-b:a",
                    "48k",
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            silence_path.unlink(missing_ok=True)

    def _write_silence_chunk(self, output_path: Path) -> None:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=24000:cl=mono",
                "-t",
                str(self._CHUNK_PAUSE_SECONDS),
                "-acodec",
                "libmp3lame",
                "-b:a",
                "48k",
                "-ar",
                "24000",
                "-ac",
                "1",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def _probe_duration(self, audio_path: Path) -> float | None:
        if shutil.which("ffprobe") is None:
            return None

        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        return float(payload["format"]["duration"])


def split_tts_chunks(text: str, max_chars: int = 60, max_words: int = 12) -> list[str]:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return []

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?…。！？])\s+", normalized)
        if part.strip()
    ]
    chunks: list[str] = []

    for sentence in sentences or [normalized]:
        chunks.extend(_split_tts_sentence(sentence, max_chars, max_words))

    return chunks or [normalized]


def _tts_chunk_fits(text: str, max_chars: int, max_words: int) -> bool:
    return len(text) <= max_chars and len(text.split()) <= max_words


def _minimum_tts_duration_seconds(text: str) -> float:
    words = len(text.split())
    chars = len(text)
    if words <= 2 and chars <= 16:
        return 0.15
    estimated_duration = max(0.25, min(words * 0.12, chars * 0.015))
    return estimated_duration * 0.85


def _prepare_edge_tts_chunk(text: str) -> str:
    prepared = re.sub(r"[,;:]+\s*$", "", text).strip()
    if prepared and _is_tiny_tts_chunk(prepared) and not re.search(r"[.!?…。！？]$", prepared):
        return f"{prepared}."
    return prepared or text


def _is_tiny_tts_chunk(text: str) -> bool:
    return len(text.split()) <= 2 and len(text) <= 16


def _split_tts_sentence(text: str, max_chars: int, max_words: int) -> list[str]:
    if _tts_chunk_fits(text, max_chars, max_words):
        return [text]

    clauses = [
        part.strip()
        for part in re.split(r"(?<=[,;:])\s+", text)
        if part.strip()
    ]
    if len(clauses) <= 1:
        return _split_long_tts_text(text, max_chars, max_words)

    chunks: list[str] = []
    for clause in clauses:
        if not _tts_chunk_fits(clause, max_chars, max_words):
            chunks.extend(_split_long_tts_text(clause, max_chars, max_words))
            continue
        chunks.append(clause)
    return chunks


def _split_long_tts_text(text: str, max_chars: int, max_words: int) -> list[str]:
    chunks: list[str] = []
    current_words: list[str] = []
    for word in text.split():
        candidate_words = [*current_words, word]
        candidate_text = " ".join(candidate_words)
        if current_words and not _tts_chunk_fits(candidate_text, max_chars, max_words):
            chunks.append(" ".join(current_words))
            current_words = [word]
        else:
            current_words = candidate_words

    if current_words:
        chunks.append(" ".join(current_words))
    if len(chunks) >= 2 and len(chunks[-1].split()) <= 2:
        candidate = f"{chunks[-2]} {chunks[-1]}"
        if _tts_chunk_fits(candidate, int(max_chars * 1.25), max_words + 3):
            chunks[-2] = candidate
            chunks.pop()
    return chunks
