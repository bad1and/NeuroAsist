import asyncio
import array
import io
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from apps.backend.app.voice.style import VoiceExpressionLevel, VoiceStyle, coerce_voice_expression_level, coerce_voice_style, make_silero_ssml, profile_for
from apps.backend.app.voice.lexicon import apply_pronunciations, load_pronunciations

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True, slots=True)
class TTSRequest:
    text: str
    language: str
    voice: str
    style: VoiceStyle | str = VoiceStyle.AUTO
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"


@dataclass(frozen=True, slots=True)
class AudioChunk:
    data: bytes
    format: str
    sequence: int
    is_final: bool = False
    metadata: dict | None = None


class STTProvider:
    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        raise NotImplementedError

    async def preload(self) -> None:
        return None


class TTSProvider:
    @property
    def name(self) -> str:
        return self.__class__.__name__.removesuffix("Provider").lower()

    @property
    def output_format(self) -> str:
        return "wav"

    @property
    def file_extension(self) -> str:
        return ".wav"

    async def preload(self) -> None:
        return None

    def resolve_voice(self, language: str, requested_voice: str | None = None) -> str:
        return requested_voice or language

    async def synthesize(
        self, text: str, voice: str, output_path: Path, style: VoiceStyle | str = VoiceStyle.AUTO
    ) -> TTSResult:
        raise NotImplementedError

    async def stream(self, request: TTSRequest):
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
    @property
    def name(self) -> str:
        return "mock"

    async def stream(self, request: TTSRequest):
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 1600)
        yield AudioChunk(output.getvalue(), "wav", 0, is_final=True)

    async def synthesize(
        self, text: str, voice: str, output_path: Path, style: VoiceStyle | str = VoiceStyle.AUTO
    ) -> TTSResult:
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
        self._selected_device: str | None = None
        self._selected_compute_type: str | None = None

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
            candidates = [(self._device, self._compute_type)]
            if self._device == "auto":
                candidates = [("cuda", "int8_float16"), ("cpu", "int8")]
            last_error: Exception | None = None
            for device, compute_type in candidates:
                try:
                    self._model = WhisperModel(
                        self._model_name,
                        device=device,
                        compute_type=compute_type,
                    )
                    self._selected_device = device
                    self._selected_compute_type = compute_type
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "FasterWhisper model load failed: model=%s device=%s compute_type=%s error_type=%s",
                        self._model_name,
                        device,
                        compute_type,
                        type(exc).__name__,
                    )
            if self._model is None:
                raise RuntimeError("faster-whisper model could not be loaded") from last_error
        return self._model

    def _transcribe_sync(self, audio_path: Path, language: str, started: float) -> STTResult:
        try:
            return self._transcribe_with_current_model(audio_path, language, started)
        except Exception as exc:
            if not self._should_retry_stt_on_cpu(exc):
                raise
            logger.info(
                "FasterWhisper CUDA runtime failed, retrying on CPU: model=%s "
                "device=%s compute_type=%s error_type=%s",
                self._model_name,
                self._selected_device,
                self._selected_compute_type,
                type(exc).__name__,
            )
            self._model = None
            self._device = "cpu"
            self._compute_type = "int8"
            self._selected_device = None
            self._selected_compute_type = None
            return self._transcribe_with_current_model(audio_path, language, started)

    def _transcribe_with_current_model(self, audio_path: Path, language: str, started: float) -> STTResult:
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

    def _should_retry_stt_on_cpu(self, exc: Exception) -> bool:
        if self._device != "auto" or self._selected_device != "cuda":
            return False
        message = str(exc).lower()
        cuda_markers = (
            "cuda",
            "cublas",
            "cudnn",
            "cufft",
            "curand",
            "cusolver",
            "cusparse",
            ".dll",
            "library",
        )
        return any(marker in message for marker in cuda_markers)


class GigaAMSTTProvider(STTProvider):
    """Russian-first local ASR backed by GigaAM v3."""

    _SAMPLE_RATE = 16000
    _MAX_SHORT_SECONDS = 24

    def __init__(self, model_name: str, device: str) -> None:
        if device not in {"cpu", "cuda", "auto"}:
            raise ValueError("VOICE_STT_DEVICE must be one of: cpu, cuda, auto")
        self._model_name = model_name
        self._device = device
        self._model = None
        self._selected_device: str | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    async def transcribe(self, audio_path: Path, language: str) -> STTResult:
        started = time.perf_counter()
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language, started)

    async def preload(self) -> None:
        await asyncio.to_thread(self._ensure_model)

    def _ensure_model(self):
        try:
            import gigaam
        except ImportError as exc:
            raise RuntimeError("GigaAM is not installed") from exc

        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            candidates = [self._device]
            if self._device == "auto":
                candidates = ["cuda", "cpu"]
            last_error: Exception | None = None
            for device in candidates:
                try:
                    self._model = gigaam.load_model(
                        self._model_name,
                        device=device,
                        fp16_encoder=device == "cuda",
                        use_flash=False,
                    )
                    self._selected_device = device
                    logger.info(
                        "GigaAM STT model loaded: model=%s device=%s",
                        self._model_name,
                        device,
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "GigaAM model load failed: model=%s device=%s error_type=%s",
                        self._model_name,
                        device,
                        type(exc).__name__,
                    )
            if self._model is None:
                raise RuntimeError("GigaAM model could not be loaded") from last_error
        return self._model

    def _transcribe_sync(self, audio_path: Path, language: str, started: float) -> STTResult:
        with self._inference_lock:
            try:
                text = self._transcribe_with_current_model(audio_path)
            except Exception as exc:
                if not self._should_retry_on_cpu(exc):
                    raise
                logger.info(
                    "GigaAM CUDA runtime failed, retrying on CPU: model=%s error_type=%s",
                    self._model_name,
                    type(exc).__name__,
                )
                self._model = None
                self._device = "cpu"
                self._selected_device = None
                text = self._transcribe_with_current_model(audio_path)
        return STTResult(
            text=text,
            language="ru" if language == "auto" else language,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="gigaam",
            model=self._model_name,
        )

    def _transcribe_with_current_model(self, audio_path: Path) -> str:
        model = self._ensure_model()
        try:
            return self._transcribe_short(model, audio_path)
        except ValueError as exc:
            if "too long wav" not in str(exc).lower():
                raise
        return self._transcribe_long(model, audio_path)

    @staticmethod
    def _transcribe_short(model: Any, audio_path: Path) -> str:
        result = model.transcribe(str(audio_path))
        return str(getattr(result, "text", result)).strip()

    def _transcribe_long(self, model: Any, audio_path: Path) -> str:
        pcm16 = self._decode_pcm16(audio_path)
        chunks = self._split_pcm16_on_quiet(pcm16)
        texts: list[str] = []
        with tempfile.TemporaryDirectory(prefix="neuroasist-gigaam-") as temp_dir:
            for index, chunk in enumerate(chunks):
                chunk_path = Path(temp_dir) / f"chunk-{index:03d}.wav"
                with wave.open(str(chunk_path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(self._SAMPLE_RATE)
                    audio.writeframes(chunk)
                text = self._transcribe_short(model, chunk_path)
                if text:
                    texts.append(text)
        return " ".join(texts).strip()

    def _decode_pcm16(self, audio_path: Path) -> bytes:
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(audio_path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(self._SAMPLE_RATE),
            "-",
        ]
        completed = subprocess.run(command, capture_output=True, check=False)
        if completed.returncode != 0 or not completed.stdout:
            raise RuntimeError("Could not decode long audio for GigaAM")
        return completed.stdout

    def _split_pcm16_on_quiet(self, pcm16: bytes) -> list[bytes]:
        samples = array.array("h")
        samples.frombytes(pcm16)
        max_samples = self._MAX_SHORT_SECONDS * self._SAMPLE_RATE
        if len(samples) <= max_samples:
            return [pcm16]

        min_chunk = 16 * self._SAMPLE_RATE
        max_chunk = 23 * self._SAMPLE_RATE
        min_tail = 5 * self._SAMPLE_RATE
        frame = self._SAMPLE_RATE // 10
        chunks: list[bytes] = []
        start = 0
        while len(samples) - start > max_samples:
            search_start = start + min_chunk
            search_end = min(start + max_chunk, len(samples) - min_tail)
            if search_end <= search_start:
                cut = min(start + max_chunk, len(samples))
            else:
                candidates = range(search_start, search_end - frame + 1, frame)
                quiet_start = min(
                    candidates,
                    key=lambda offset: sum(value * value for value in samples[offset : offset + frame]),
                )
                cut = quiet_start + frame // 2
            chunks.append(samples[start:cut].tobytes())
            start = cut
        if start < len(samples):
            chunks.append(samples[start:].tobytes())
        return chunks

    def _should_retry_on_cpu(self, exc: Exception) -> bool:
        if self._device != "auto" or self._selected_device != "cuda":
            return False
        message = str(exc).lower()
        return any(
            marker in message
            for marker in ("cuda", "cublas", "cudnn", "out of memory", "driver")
        )


def waveform_to_wav_bytes(waveform: Any, sample_rate: int) -> bytes:
    import numpy as np

    value = waveform
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        samples = value.numpy()
    else:
        samples = np.asarray(value)
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(pcm.tobytes())
    return output.getvalue()


def wav_duration_seconds(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as audio:
        frames = audio.getnframes()
        rate = audio.getframerate()
        if frames <= 0 or rate <= 0:
            raise RuntimeError("TTS provider returned zero-duration audio")
        return frames / rate


_RU_UNITS = (
    "ноль",
    "один",
    "два",
    "три",
    "четыре",
    "пять",
    "шесть",
    "семь",
    "восемь",
    "девять",
    "десять",
    "одиннадцать",
    "двенадцать",
    "тринадцать",
    "четырнадцать",
    "пятнадцать",
    "шестнадцать",
    "семнадцать",
    "восемнадцать",
    "девятнадцать",
)
_RU_TENS = ("", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто")
_RU_HUNDREDS = ("", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот")
_RU_SCALES = (
    ("", "", "", False),
    ("тысяча", "тысячи", "тысяч", True),
    ("миллион", "миллиона", "миллионов", False),
    ("миллиард", "миллиарда", "миллиардов", False),
    ("триллион", "триллиона", "триллионов", False),
)
_RU_DIGITS = tuple(_RU_UNITS[:10])


def _ru_plural_form(number: int, forms: tuple[str, str, str]) -> str:
    last_two = number % 100
    if 11 <= last_two <= 14:
        return forms[2]
    last = number % 10
    if last == 1:
        return forms[0]
    if 2 <= last <= 4:
        return forms[1]
    return forms[2]


def _ru_triplet(number: int, *, feminine: bool = False) -> list[str]:
    words: list[str] = []
    hundreds, remainder = divmod(number, 100)
    if hundreds:
        words.append(_RU_HUNDREDS[hundreds])
    if remainder < 20:
        if remainder:
            if feminine and remainder == 1:
                words.append("одна")
            elif feminine and remainder == 2:
                words.append("две")
            else:
                words.append(_RU_UNITS[remainder])
        return words
    tens, units = divmod(remainder, 10)
    words.append(_RU_TENS[tens])
    if units:
        if feminine and units == 1:
            words.append("одна")
        elif feminine and units == 2:
            words.append("две")
        else:
            words.append(_RU_UNITS[units])
    return words


def integer_to_russian_words(value: int, *, original_digits: str | None = None) -> str:
    digits = original_digits or str(abs(value))
    unsigned_digits = digits.lstrip("+-")
    if (len(unsigned_digits) > 1 and unsigned_digits.startswith("0")) or len(unsigned_digits) > 15:
        prefix = "минус " if value < 0 else ""
        return prefix + " ".join(_RU_DIGITS[int(digit)] for digit in unsigned_digits if digit.isdigit())
    if value == 0:
        return _RU_UNITS[0]

    prefix = ["минус"] if value < 0 else []
    remaining = abs(value)
    groups: list[int] = []
    while remaining:
        remaining, group = divmod(remaining, 1000)
        groups.append(group)
    if len(groups) > len(_RU_SCALES):
        return " ".join(_RU_DIGITS[int(digit)] for digit in unsigned_digits)

    words = prefix
    for scale_index in range(len(groups) - 1, -1, -1):
        group = groups[scale_index]
        if not group:
            continue
        scale = _RU_SCALES[scale_index]
        words.extend(_ru_triplet(group, feminine=scale[3]))
        if scale_index:
            words.append(_ru_plural_form(group, scale[:3]))
    return " ".join(words)


_IPV4_PATTERN = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?!\d|\.\d)")
_DOTTED_NUMBER_PATTERN = re.compile(r"(?<![\d.])(\d+(?:\.\d+){2,})(?!\d|\.\d)")
_TECH_PAIR_NUMBER_PATTERN = re.compile(
    r"(?i)\b((?:порт(?:а|у|ом|е)?|(?:rtx|gtx|rx))\s+)(\d{4})\b"
)
_YEAR_PATTERN = re.compile(
    r"(?i)(?<!\d)((?:19|20)\d{2})(\s+)(год|года|году|годом|годе)\b"
)
_DATE_PATTERN = re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])[./-](0?[1-9]|1[0-2])[./-]((?:19|20)\d{2})(?!\d)")
_NUMBER_PATTERN = re.compile(r"(?<!\d)([+-]?\d+(?:[.,]\d+)?)(%?)(?!\d)")

_RU_ORDINALS = {
    1: "первый", 2: "второй", 3: "третий", 4: "четвёртый", 5: "пятый",
    6: "шестой", 7: "седьмой", 8: "восьмой", 9: "девятый", 10: "десятый",
    11: "одиннадцатый", 12: "двенадцатый", 13: "тринадцатый",
    14: "четырнадцатый", 15: "пятнадцатый", 16: "шестнадцатый",
    17: "семнадцатый", 18: "восемнадцатый", 19: "девятнадцатый",
    20: "двадцатый", 30: "тридцатый", 40: "сороковой", 50: "пятидесятый",
    60: "шестидесятый", 70: "семидесятый", 80: "восьмидесятый",
    90: "девяностый",
}


def _ru_ordinal_under_hundred(value: int) -> str:
    if value in _RU_ORDINALS:
        return _RU_ORDINALS[value]
    tens, units = divmod(value, 10)
    return f"{_RU_TENS[tens]} {_RU_ORDINALS[units]}"


def _decline_year_ordinal(ordinal: str, year_noun: str) -> str:
    if year_noun == "год":
        return ordinal
    if ordinal.endswith("третий"):
        endings = {"года": "третьего", "году": "третьем", "годом": "третьим", "годе": "третьем"}
        return ordinal.removesuffix("третий") + endings[year_noun]
    stem = ordinal[:-2]
    endings = {"года": "ого", "году": "ом", "годом": "ым", "годе": "ом"}
    return stem + endings[year_noun]


def _year_to_russian_words(year: int, year_noun: str) -> str:
    if year == 2000:
        ordinal = "двухтысячный"
        return _decline_year_ordinal(ordinal, year_noun)
    if year == 1900:
        ordinal = "тысяча девятисотый"
        return _decline_year_ordinal(ordinal, year_noun)
    if 2000 < year < 2100:
        prefix = "две тысячи"
        ordinal = _ru_ordinal_under_hundred(year - 2000)
    else:
        prefix = "тысяча девятьсот"
        remainder = year - 1900
        ordinal = _ru_ordinal_under_hundred(remainder)
    return f"{prefix} {_decline_year_ordinal(ordinal, year_noun)}"


_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def _date_day_words(day: int) -> str:
    ordinal = _ru_ordinal_under_hundred(day)
    if ordinal.endswith("третий"):
        return ordinal.removesuffix("третий") + "третье"
    if ordinal.endswith("ый"):
        return ordinal[:-2] + "ое"
    if ordinal.endswith("ий"):
        return ordinal[:-2] + "ее"
    if ordinal.endswith("ой"):
        return ordinal[:-2] + "ое"
    return ordinal


def expand_russian_numbers(text: str) -> str:
    def replace_date(match: re.Match[str]) -> str:
        day, month, year = (int(value) for value in match.groups())
        return f"{_date_day_words(day)} {_MONTHS_GENITIVE[month - 1]} {_year_to_russian_words(year, 'года')} года"

    def replace_year(match: re.Match[str]) -> str:
        year, spacing, year_noun = match.groups()
        return f"{_year_to_russian_words(int(year), year_noun.lower())}{spacing}{year_noun}"

    def replace_dotted(match: re.Match[str]) -> str:
        return " точка ".join(
            integer_to_russian_words(int(part), original_digits=part)
            for part in match.group(1).split(".")
        )

    def replace_tech_pair(match: re.Match[str]) -> str:
        prefix, digits = match.groups()
        left, right = digits[:2], digits[2:]
        if int(left) < 10 or int(right) < 10:
            return match.group(0)
        return (
            f"{prefix}{integer_to_russian_words(int(left), original_digits=left)}, "
            f"{integer_to_russian_words(int(right), original_digits=right)}"
        )

    def replace(match: re.Match[str]) -> str:
        raw_number, percent = match.groups()
        sign = -1 if raw_number.startswith("-") else 1
        unsigned = raw_number.lstrip("+-")
        if "." in unsigned or "," in unsigned:
            integer_part, fractional_part = re.split(r"[.,]", unsigned, maxsplit=1)
            integer_value = sign * int(integer_part or "0")
            result = (
                f"{integer_to_russian_words(integer_value, original_digits=integer_part)} "
                f"точка {integer_to_russian_words(int(fractional_part), original_digits=fractional_part)}"
            )
        else:
            integer_value = sign * int(unsigned)
            result = integer_to_russian_words(integer_value, original_digits=unsigned)
        if percent:
            result += " " + _ru_plural_form(abs(int(float(raw_number.replace(",", ".")))), ("процент", "процента", "процентов"))
        return result

    normalized = _DATE_PATTERN.sub(replace_date, text)
    normalized = _YEAR_PATTERN.sub(replace_year, normalized)
    normalized = _IPV4_PATTERN.sub(replace_dotted, normalized)
    normalized = _DOTTED_NUMBER_PATTERN.sub(replace_dotted, normalized)
    normalized = _TECH_PAIR_NUMBER_PATTERN.sub(replace_tech_pair, normalized)
    return _NUMBER_PATTERN.sub(replace, normalized)


_ENGLISH_LETTER_NAMES = {
    "a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф", "g": "джи",
    "h": "эйч", "i": "ай", "j": "джей", "k": "кей", "l": "эл", "m": "эм", "n": "эн",
    "o": "оу", "p": "пи", "q": "кью", "r": "ар", "s": "эс", "t": "ти", "u": "ю",
    "v": "ви", "w": "дабл ю", "x": "экс", "y": "уай", "z": "зи",
}
_TECH_WORDS_RU = {
    "ai": "эй ай",
    "api": "эй пи ай",
    "cpu": "си пи ю",
    "cuda": "кьюда",
    "docker": "докер",
    "github": "гитхаб",
    "gpu": "джи пи ю",
    "http": "эйч ти ти пи",
    "https": "эйч ти ти пи эс",
    "json": "джейсон",
    "linux": "линукс",
    "llm": "эл эл эм",
    "neuroasist": "нейро асист",
    "nvidia": "энвидиа",
    "openai": "оупен эй ай",
    "python": "пайтон",
    "sql": "эс кью эл",
    "stt": "эс ти ти",
    "tts": "ти ти эс",
    "ui": "ю ай",
    "url": "ю ар эл",
    "usb": "ю эс би",
    "windows": "уиндоус",
    "wifi": "вай фай",
}
_ENGLISH_MULTIGRAPHS = (
    ("tion", "шн"), ("sion", "жн"), ("ture", "чер"), ("eigh", "эй"),
    ("igh", "ай"), ("air", "эйр"), ("ear", "ир"), ("tch", "ч"),
    ("ph", "ф"), ("sh", "ш"), ("ch", "ч"), ("th", "с"), ("ck", "к"),
    ("qu", "кв"), ("ng", "нг"), ("ee", "и"), ("ea", "и"), ("oo", "у"),
    ("ou", "ау"), ("ow", "ау"), ("ai", "эй"), ("ay", "эй"), ("oi", "ой"),
    ("oy", "ой"), ("au", "о"),
)
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")

_CMUDICT_REVISION = "74790861f652b15e4ac49015a90074ad62a27690"
_CMUDICT_PATH: Path | None = None
_CMUDICT_ENTRIES: dict[str, list[str]] | None = None
_CMUDICT_LOCK = threading.Lock()
_ARPABET_TO_CYRILLIC = {
    "AA": "а", "AE": "э", "AH": "э", "AO": "о", "AW": "ау",
    "AY": "ай", "B": "б", "CH": "ч", "D": "д", "DH": "з",
    "EH": "э", "ER": "эр", "EY": "эй", "F": "ф", "G": "г",
    "HH": "х", "IH": "и", "IY": "и", "JH": "дж", "K": "к",
    "L": "л", "M": "м", "N": "н", "NG": "нг", "OW": "оу",
    "OY": "ой", "P": "п", "R": "р", "S": "с", "SH": "ш",
    "T": "т", "TH": "с", "UH": "у", "UW": "у", "V": "в",
    "W": "у", "Y": "й", "Z": "з", "ZH": "ж",
}


def configure_cmudict(path: Path) -> None:
    global _CMUDICT_PATH, _CMUDICT_ENTRIES
    resolved = path.resolve()
    with _CMUDICT_LOCK:
        if _CMUDICT_PATH != resolved:
            _CMUDICT_PATH = resolved
            _CMUDICT_ENTRIES = None


def _load_cmudict_entries() -> dict[str, list[str]]:
    global _CMUDICT_ENTRIES
    with _CMUDICT_LOCK:
        if _CMUDICT_ENTRIES is not None:
            return _CMUDICT_ENTRIES
        entries: dict[str, list[str]] = {}
        if _CMUDICT_PATH is not None and _CMUDICT_PATH.is_file():
            with _CMUDICT_PATH.open("r", encoding="utf-8", errors="ignore") as dictionary:
                for raw_line in dictionary:
                    line = raw_line.strip()
                    if not line or line.startswith(";;;"):
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    word = re.sub(r"\(\d+\)$", "", parts[0].lower())
                    entries.setdefault(word, parts[1:])
        _CMUDICT_ENTRIES = entries
        return entries


def _cmudict_word_to_cyrillic(word: str) -> str | None:
    phonemes = _load_cmudict_entries().get(word.lower())
    if not phonemes:
        return None
    rendered: list[str] = []
    for phoneme in phonemes:
        base = re.sub(r"\d", "", phoneme)
        value = _ARPABET_TO_CYRILLIC.get(base)
        if value:
            rendered.append(value)
    return "".join(rendered) or None

def _english_word_to_cyrillic(word: str) -> str:
    lower = word.lower().replace("'", "").replace("’", "")
    known = _TECH_WORDS_RU.get(lower)
    if known:
        return known
    if len(lower) == 1 or (word.isupper() and len(lower) <= 8):
        return " ".join(_ENGLISH_LETTER_NAMES[letter] for letter in lower)
    dictionary_pronunciation = _cmudict_word_to_cyrillic(lower)
    if dictionary_pronunciation:
        return dictionary_pronunciation
    if len(lower) > 3 and lower.endswith("e"):
        lower = lower[:-1]
    for source, target in _ENGLISH_MULTIGRAPHS:
        lower = lower.replace(source, target)

    output: list[str] = []
    for index, char in enumerate(lower):
        if not ("a" <= char <= "z"):
            output.append(char)
            continue
        next_char = lower[index + 1] if index + 1 < len(lower) else ""
        if char == "c":
            output.append("с" if next_char in "eiy" else "к")
        elif char == "g":
            output.append("дж" if next_char in "eiy" else "г")
        else:
            output.append({
                "a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "h": "х",
                "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
                "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т",
                "u": "у", "v": "в", "w": "у", "x": "кс", "y": "и", "z": "з",
            }.get(char, char))
    return "".join(output)


def transliterate_english_for_russian_tts(text: str) -> str:
    return _LATIN_WORD_PATTERN.sub(lambda match: _english_word_to_cyrillic(match.group(0)), text)


def normalize_russian_tts_text(
    text: str, *, transliterate_latin: bool = True, pronunciations: dict[str, str] | None = None
) -> str:
    normalized = " ".join(text.strip().split())
    if pronunciations:
        normalized = apply_pronunciations(normalized, pronunciations)
    normalized = expand_russian_numbers(normalized)
    if transliterate_latin:
        normalized = transliterate_english_for_russian_tts(normalized)
    return " ".join(normalized.split())


_ENGLISH_RUN_PATTERN = re.compile(
    r"[A-Za-z]+(?:['’-][A-Za-z]+)*(?:\s+(?:[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:[._-]\d+)*))*"
)
_RUSSIAN_OR_NUMBER_PATTERN = re.compile(r"[А-Яа-яЁё\d]")


def split_multilingual_tts_segments(text: str, language: str = "ru") -> list[tuple[str, str]]:
    """Split Russian text into native RU/EN runs without synthesizing punctuation alone."""
    normalized = " ".join(text.strip().split())
    if not normalized:
        return []
    if language.lower().startswith("en"):
        return [("en", normalized)]

    raw_segments: list[tuple[str, str]] = []
    cursor = 0
    for match in _ENGLISH_RUN_PATTERN.finditer(normalized):
        if match.start() > cursor:
            raw_segments.append(("ru", normalized[cursor:match.start()]))
        raw_segments.append(("en", match.group(0)))
        cursor = match.end()
    if cursor < len(normalized):
        raw_segments.append(("ru", normalized[cursor:]))
    if not raw_segments:
        raw_segments.append(("ru", normalized))

    segments: list[tuple[str, str]] = []
    pending_prefix = ""
    for segment_language, segment_text in raw_segments:
        if (
            segment_language == "ru"
            and not _RUSSIAN_OR_NUMBER_PATTERN.search(segment_text)
        ):
            if segments:
                previous_language, previous_text = segments[-1]
                segments[-1] = (previous_language, previous_text + segment_text)
            else:
                pending_prefix += segment_text
            continue
        prepared = pending_prefix + segment_text
        pending_prefix = ""
        if segments and segments[-1][0] == segment_language:
            segments[-1] = (segment_language, segments[-1][1] + prepared)
        else:
            segments.append((segment_language, prepared))
    if pending_prefix and segments:
        previous_language, previous_text = segments[-1]
        segments[-1] = (previous_language, previous_text + pending_prefix)

    return [
        (
            segment_language,
            normalize_russian_tts_text(segment_text, transliterate_latin=False)
            if segment_language == "ru"
            else " ".join(segment_text.strip().split()),
        )
        for segment_language, segment_text in segments
        if segment_text.strip()
    ]


def prepare_english_tts_text(text: str) -> str:
    pronunciation_overrides = {
        "neuroasist": "Neuro Assist",
        "openai": "Open A I",
        "python": "Pie thon",
        "github": "Git Hub",
    }
    prepared = _LATIN_WORD_PATTERN.sub(
        lambda match: pronunciation_overrides.get(
            match.group(0).lower(),
            match.group(0),
        ),
        text,
    )
    prepared = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", prepared)
    prepared = re.sub(
        r"\b[A-Z]{2,}\b",
        lambda match: " ".join(match.group(0)),
        prepared,
    )
    return " ".join(prepared.strip().split())


class OpenVoiceToneConverter:
    """CPU-only OpenVoice V2 tone conversion used after fast Silero synthesis."""

    def __init__(
        self,
        *,
        reference_audio_path: Path,
        cache_dir: Path,
        repo_id: str,
        revision: str,
        tau: float = 0.3,
        cpu_threads: int = 8,
    ) -> None:
        self.reference_audio_path = reference_audio_path
        self.cache_dir = cache_dir
        self.repo_id = repo_id
        self.revision = revision
        self.tau = tau
        self.cpu_threads = cpu_threads
        self.sample_rate = 22050
        self.filter_length = 1024
        self.hop_length = 256
        self.win_length = 1024
        self._torch = None
        self._torchaudio = None
        self._spectrogram_torch = None
        self._model = None
        self._target_embedding = None

    def load(self) -> None:
        reference_path = self.reference_audio_path.resolve()
        if not reference_path.is_file():
            raise RuntimeError(f"OpenVoice reference audio does not exist: {reference_path}")
        config_path, checkpoint_path = self._ensure_checkpoint()
        try:
            import soundfile
            import torch
            import torchaudio
            from openvoice import utils as openvoice_utils
            from openvoice.mel_processing import spectrogram_torch
            from openvoice.models import SynthesizerTrn
        except ImportError as exc:
            raise RuntimeError(
                "OpenVoice tone conversion is not installed. Run scripts/install-openvoice.ps1."
            ) from exc

        if self.cpu_threads > 0:
            torch.set_num_threads(self.cpu_threads)
        hps = openvoice_utils.get_hparams_from_file(str(config_path))
        model = SynthesizerTrn(
            len(getattr(hps, "symbols", [])),
            hps.data.filter_length // 2 + 1,
            n_speakers=hps.data.n_speakers,
            **hps.model,
        ).to("cpu")
        checkpoint = torch.load(
            str(checkpoint_path),
            map_location=torch.device("cpu"),
            weights_only=False,
        )
        missing, unexpected = model.load_state_dict(checkpoint["model"], strict=False)
        if missing or unexpected:
            raise RuntimeError(
                f"OpenVoice checkpoint is incompatible: missing={missing}, unexpected={unexpected}"
            )
        model.eval()
        self.sample_rate = int(hps.data.sampling_rate)
        self.filter_length = int(hps.data.filter_length)
        self.hop_length = int(hps.data.hop_length)
        self.win_length = int(hps.data.win_length)
        self._torch = torch
        self._torchaudio = torchaudio
        self._spectrogram_torch = spectrogram_torch
        self._model = model
        reference_audio, reference_rate = soundfile.read(
            str(reference_path),
            dtype="float32",
            always_2d=True,
        )
        reference = torch.from_numpy(reference_audio.mean(axis=1))
        self._target_embedding = self._extract_embedding(reference, int(reference_rate))

    def _ensure_checkpoint(self) -> tuple[Path, Path]:
        converter_dir = self.cache_dir.resolve() / "converter"
        config_path = converter_dir / "config.json"
        checkpoint_path = converter_dir / "checkpoint.pth"
        if config_path.is_file() and checkpoint_path.is_file():
            return config_path, checkpoint_path
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError("OpenVoice download requires huggingface_hub") from exc
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=self.repo_id,
            revision=self.revision,
            allow_patterns=["converter/*"],
            local_dir=str(self.cache_dir.resolve()),
        )
        if not config_path.is_file() or not checkpoint_path.is_file():
            raise RuntimeError("OpenVoice converter checkpoint download is incomplete")
        return config_path, checkpoint_path

    def _resample(self, waveform: Any, sample_rate: int):
        if self._torch is None or self._torchaudio is None:
            raise RuntimeError("OpenVoice converter is not loaded")
        value = waveform
        if not hasattr(value, "detach"):
            value = self._torch.as_tensor(value)
        value = value.detach().to(device="cpu", dtype=self._torch.float32).squeeze()
        if value.ndim > 1:
            value = value.mean(dim=0)
        if sample_rate != self.sample_rate:
            value = self._torchaudio.functional.resample(
                value,
                sample_rate,
                self.sample_rate,
            )
        return value.contiguous()

    def _spectrogram(self, waveform):
        if self._model is None or self._spectrogram_torch is None:
            raise RuntimeError("OpenVoice converter is not loaded")
        return self._spectrogram_torch(
            waveform.unsqueeze(0),
            self.filter_length,
            self.sample_rate,
            self.hop_length,
            self.win_length,
            center=False,
        )

    def _extract_embedding(self, waveform: Any, sample_rate: int):
        if self._torch is None or self._model is None:
            raise RuntimeError("OpenVoice converter is not loaded")
        prepared = self._resample(waveform, sample_rate)
        with self._torch.inference_mode():
            spectrogram = self._spectrogram(prepared)
            return self._model.ref_enc(spectrogram.transpose(1, 2)).unsqueeze(-1).detach()

    def convert(self, waveform: Any, sample_rate: int):
        if self._torch is None or self._model is None or self._target_embedding is None:
            raise RuntimeError("OpenVoice converter is not loaded")
        prepared = self._resample(waveform, sample_rate)
        with self._torch.inference_mode():
            spectrogram = self._spectrogram(prepared)
            lengths = self._torch.LongTensor([spectrogram.size(-1)])
            source_embedding = self._model.ref_enc(
                spectrogram.transpose(1, 2)
            ).unsqueeze(-1)
            converted = self._model.voice_conversion(
                spectrogram,
                lengths,
                sid_src=source_embedding,
                sid_tgt=self._target_embedding,
                tau=self.tau,
            )[0][0, 0]
        return converted.detach().cpu()


_SILERO_RU_FEMALE_SPEAKERS = ("xenia", "baya", "kseniya")


class SileroTTSProvider(TTSProvider):
    def __init__(
        self,
        model: str = "v5_5_ru",
        speaker: str = "xenia",
        sample_rate: int = 24000,
        device: str = "cpu",
        cpu_threads: int = 4,
        warmup: bool = True,
        timeout_seconds: float = 10.0,
        loudness_target_dbfs: float = -18.0,
        peak_ceiling_dbfs: float = -1.0,
        pronunciation_dictionary_path: Path | None = None,
        native_english: bool = False,
        english_model: str = "v3_en",
        english_speaker: str = "en_0",
        cmudict_enabled: bool = True,
        cmudict_cache_dir: Path | None = None,
        openvoice_enabled: bool = False,
        openvoice_reference_audio_path: Path | None = None,
        openvoice_cache_dir: Path | None = None,
        openvoice_repo_id: str = "myshell-ai/OpenVoiceV2",
        openvoice_revision: str = "fd981100305a0e4291f93a9ad169c6d9f7bed54a",
        openvoice_tau: float = 0.3,
        openvoice_cpu_threads: int = 8,
        model_loader: Callable[[], Any] | None = None,
        english_model_loader: Callable[[], Any] | None = None,
        voice_converter_loader: Callable[[], Any] | None = None,
    ) -> None:
        if device not in {"cpu", "cuda", "auto"}:
            raise ValueError("VOICE_SILERO_DEVICE must be one of: cpu, cuda, auto")
        self.model_name = model
        self.speaker = speaker
        self.sample_rate = sample_rate
        self.requested_device = device
        self.cpu_threads = cpu_threads
        self.warmup_enabled = warmup
        self.timeout_seconds = timeout_seconds
        self.loudness_target_dbfs = loudness_target_dbfs
        self.peak_ceiling_dbfs = peak_ceiling_dbfs
        self.pronunciation_dictionary_path = pronunciation_dictionary_path
        self.native_english = native_english
        self.english_model_name = english_model
        self.english_speaker = english_speaker
        self.cmudict_enabled = cmudict_enabled
        self.cmudict_cache_dir = cmudict_cache_dir or Path(".cache/cmudict")
        self.openvoice_enabled = openvoice_enabled
        self.openvoice_reference_audio_path = openvoice_reference_audio_path
        self.openvoice_cache_dir = openvoice_cache_dir or Path(".cache/openvoice-v2")
        self.openvoice_repo_id = openvoice_repo_id
        self.openvoice_revision = openvoice_revision
        self.openvoice_tau = openvoice_tau
        self.openvoice_cpu_threads = openvoice_cpu_threads
        self._model_loader = model_loader
        self._english_model_loader = english_model_loader
        self._voice_converter_loader = voice_converter_loader
        self._model = None
        self._english_tts_model = None
        self._voice_converter = None
        if self.openvoice_enabled and self.openvoice_reference_audio_path is None:
            raise ValueError(
                "VOICE_OPENVOICE_REFERENCE_AUDIO is required when VOICE_OPENVOICE_ENABLED=true"
            )
        self._torch = None
        self._selected_device: str | None = None
        self._available_speakers: set[str] | None = None
        self._pronunciations: dict[str, str] = {}
        self._expression_level = VoiceExpressionLevel.NATURAL
        self._load_lock = asyncio.Lock()
        self._infer_lock = asyncio.Lock()
        self._warmed_up = False

    @property
    def name(self) -> str:
        return "silero"

    def resolve_voice(self, language: str, requested_voice: str | None = None) -> str:
        if requested_voice and requested_voice in self.available_speakers:
            return requested_voice
        return self.speaker

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model_name,
            "speaker": self.speaker,
            "device": self._selected_device or self.requested_device,
            "sample_rate": getattr(self._voice_converter, "sample_rate", self.sample_rate),
            "voice_conversion": self._voice_converter is not None,
            "native_english": self._english_tts_model is not None,
            "english_transcription": self.cmudict_enabled and not self.native_english,
        }

    def set_pronunciations(self, pronunciations: dict[str, str]) -> None:
        self._pronunciations = dict(pronunciations)

    def set_expression_level(self, level: str | VoiceExpressionLevel) -> None:
        self._expression_level = coerce_voice_expression_level(level)

    @property
    def available_speakers(self) -> list[str]:
        if self.model_name == "v5_5_ru":
            speakers = [
                voice
                for voice in _SILERO_RU_FEMALE_SPEAKERS
                if self._available_speakers is None or voice in self._available_speakers
            ]
            if self.speaker in speakers:
                speakers.remove(self.speaker)
                speakers.insert(0, self.speaker)
            return speakers
        if self._available_speakers is not None:
            return sorted(self._available_speakers)
        return [self.speaker]

    async def preload(self) -> None:
        await self._ensure_model()

    async def _ensure_model(self):
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is not None:
                return self._model
            started = time.perf_counter()
            model, torch_module, selected_device = await asyncio.to_thread(self._load_model_sync)
            self._model = model
            self._torch = torch_module
            self._selected_device = selected_device
            self._available_speakers = self._extract_speakers(model)
            self._validate_speaker(self.speaker)
            if self.pronunciation_dictionary_path is not None:
                self._pronunciations = await asyncio.to_thread(
                    load_pronunciations, self.pronunciation_dictionary_path
                )
            if self.cmudict_enabled and not self.native_english:
                try:
                    dictionary_size = await asyncio.to_thread(self._prepare_cmudict_sync)
                    logger.info(
                        "CMU English pronunciation dictionary loaded: entries=%s",
                        dictionary_size,
                    )
                except Exception:
                    logger.warning(
                        "CMU pronunciation dictionary is unavailable; using basic transliteration",
                        exc_info=True,
                    )
            if self.native_english:
                english_started = time.perf_counter()
                self._english_tts_model = await asyncio.to_thread(
                    self._load_english_model_sync
                )
                logger.info(
                    "Silero English TTS model loaded: load_ms=%s model=%s speaker=%s device=%s",
                    int((time.perf_counter() - english_started) * 1000),
                    self.english_model_name,
                    self.english_speaker,
                    selected_device,
                )
            if self.openvoice_enabled:
                converter_started = time.perf_counter()
                self._voice_converter = await asyncio.to_thread(
                    self._load_voice_converter_sync
                )
                logger.info(
                    "OpenVoice tone converter loaded: load_ms=%s device=cpu reference=%s",
                    int((time.perf_counter() - converter_started) * 1000),
                    self.openvoice_reference_audio_path,
                )
            load_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "Silero TTS model loaded: tts_model_load_ms=%s device=%s model=%s speaker=%s sample_rate=%s",
                load_ms,
                selected_device,
                self.model_name,
                self.speaker,
                self.sample_rate,
            )
            if self.warmup_enabled and not self._warmed_up:
                warmup_started = time.perf_counter()
                if self._english_tts_model is not None:
                    await asyncio.to_thread(self._apply_english_tts_sync, "Hello.")
                await asyncio.to_thread(self._render_sync, "Привет.", self.speaker, VoiceStyle.NORMAL)
                self._warmed_up = True
                logger.info(
                    "Silero TTS model warmed up: tts_warmup_ms=%s device=%s model=%s speaker=%s sample_rate=%s",
                    int((time.perf_counter() - warmup_started) * 1000),
                    selected_device,
                    self.model_name,
                    self.speaker,
                    self.sample_rate,
                )
            return self._model

    def _load_voice_converter_sync(self):
        if self._voice_converter_loader is not None:
            converter = self._voice_converter_loader()
        else:
            assert self.openvoice_reference_audio_path is not None
            converter = OpenVoiceToneConverter(
                reference_audio_path=self.openvoice_reference_audio_path,
                cache_dir=self.openvoice_cache_dir,
                repo_id=self.openvoice_repo_id,
                revision=self.openvoice_revision,
                tau=self.openvoice_tau,
                cpu_threads=self.openvoice_cpu_threads,
            )
        load = getattr(converter, "load", None)
        if callable(load):
            load()
        return converter

    def _load_english_model_sync(self):
        if self._torch is None or self._selected_device is None:
            raise RuntimeError("Silero Russian model must be loaded first")
        if self._english_model_loader is not None:
            model = self._english_model_loader()
        else:
            self._configure_certifi_ca_bundle()
            model, _ = self._torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="en",
                speaker=self.english_model_name,
                trust_repo=True,
            )
        if hasattr(model, "to"):
            moved_model = model.to(self._selected_device)
            if moved_model is not None:
                model = moved_model
        speakers = self._extract_speakers(model)
        if speakers is not None and self.english_speaker not in speakers:
            raise RuntimeError(f"Unknown Silero English speaker: {self.english_speaker}")
        return model

    def _prepare_cmudict_sync(self) -> int:
        import urllib.request

        cache_dir = self.cmudict_cache_dir.resolve()
        dictionary_path = cache_dir / "cmudict.dict"
        license_path = cache_dir / "LICENSE"
        base_url = (
            "https://raw.githubusercontent.com/cmusphinx/cmudict/"
            f"{_CMUDICT_REVISION}"
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        for path, name in ((dictionary_path, "cmudict.dict"), (license_path, "LICENSE")):
            if path.is_file():
                continue
            request = urllib.request.Request(
                f"{base_url}/{name}",
                headers={"User-Agent": "NeuroAsist/0.5"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
            temp_path = path.with_suffix(path.suffix + ".tmp")
            temp_path.write_bytes(payload)
            temp_path.replace(path)
        configure_cmudict(dictionary_path)
        return len(_load_cmudict_entries())

    def _load_model_sync(self):
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "Silero TTS requires torch. Install CPU PyTorch and silero before using VOICE_TTS_PROVIDER=silero."
            ) from exc
        if self.cpu_threads > 0:
            torch.set_num_threads(self.cpu_threads)
        selected_device = self._select_device(torch)
        if self._model_loader is not None:
            model = self._model_loader()
        else:
            self._configure_certifi_ca_bundle()
            try:
                model, _ = torch.hub.load(
                    repo_or_dir="snakers4/silero-models",
                    model="silero_tts",
                    language="ru",
                    speaker=self.model_name,
                    # The desktop backend has no interactive stdin. Without an
                    # explicit trust decision Torch Hub blocks startup waiting
                    # for a confirmation that cannot be entered by the user.
                    trust_repo=True,
                )
            except Exception as exc:
                message = str(exc)
                if "CERTIFICATE_VERIFY_FAILED" in message or "[SSL:" in message:
                    raise RuntimeError(
                        "Silero TTS model download failed because HTTPS certificate verification failed. "
                        "Check Windows date/time, update trusted root certificates, update certifi in the "
                        "virtual environment, and remove the incomplete torch hub cache before retrying."
                    ) from exc
                raise
        if hasattr(model, "to"):
            moved_model = model.to(selected_device)
            if moved_model is not None:
                model = moved_model
        return model, torch, selected_device

    def _configure_certifi_ca_bundle(self) -> None:
        if os.environ.get("SSL_CERT_FILE"):
            return
        try:
            import certifi
        except ImportError:
            return
        os.environ["SSL_CERT_FILE"] = certifi.where()

    def _select_device(self, torch_module) -> str:
        if self.requested_device == "cpu":
            return "cpu"
        cuda_available = bool(torch_module.cuda.is_available())
        if self.requested_device == "cuda":
            if not cuda_available:
                raise RuntimeError("VOICE_SILERO_DEVICE=cuda was requested, but CUDA is not available")
            return "cuda"
        return "cuda" if cuda_available else "cpu"

    def _extract_speakers(self, model) -> set[str] | None:
        for attr in ("speakers", "speaker_names"):
            speakers = getattr(model, attr, None)
            if speakers:
                return {str(item) for item in speakers}
        return None

    def _validate_speaker(self, speaker: str) -> None:
        if self._available_speakers is None or speaker in self._available_speakers:
            return
        logger.debug(
            "Unknown Silero speaker requested: speaker=%s available_speakers=%s",
            speaker,
            sorted(self._available_speakers),
        )
        raise RuntimeError(f"Unknown Silero speaker: {speaker}")

    def _apply_tts_sync(self, text: str, speaker: str, style: VoiceStyle | str):
        if self._model is None or self._torch is None:
            raise RuntimeError("Silero model is not loaded")
        with self._torch.inference_mode():
            normalized = normalize_russian_tts_text(text, pronunciations=self._pronunciations)
            return self._model.apply_tts(
                ssml_text=make_silero_ssml(normalized, style, self._expression_level),
                speaker=speaker,
                sample_rate=self.sample_rate,
                intensity=profile_for(style, self._expression_level).intensity,
            )

    def _apply_english_tts_sync(self, text: str):
        if self._english_tts_model is None or self._torch is None:
            raise RuntimeError("Silero English model is not loaded")
        with self._torch.inference_mode():
            return self._english_tts_model.apply_tts(
                text=prepare_english_tts_text(text),
                speaker=self.english_speaker,
                sample_rate=self.sample_rate,
            )

    @staticmethod
    def _waveform_as_numpy(waveform: Any):
        import numpy as np

        value = waveform
        if hasattr(value, "detach"):
            value = value.detach()
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            value = value.numpy()
        return np.asarray(value, dtype=np.float32).reshape(-1)

    def _render_sync(self, text: str, speaker: str, style: VoiceStyle | str) -> tuple[Any, int]:
        if self._english_tts_model is None:
            waveform = self._apply_tts_sync(text, speaker, style)
        else:
            import numpy as np

            segments = split_multilingual_tts_segments(text, "ru")
            rendered: list[Any] = []
            silence = np.zeros(int(self.sample_rate * 0.04), dtype=np.float32)
            for segment_language, segment_text in segments:
                if rendered:
                    rendered.append(silence)
                segment_waveform = (
                    self._apply_english_tts_sync(segment_text)
                    if segment_language == "en"
                    else self._apply_tts_sync(segment_text, speaker, style)
                )
                rendered.append(self._waveform_as_numpy(segment_waveform))
            if not rendered:
                raise ValueError("TTS text is empty")
            waveform = np.concatenate(rendered)
        if self._voice_converter is None:
            return waveform, self.sample_rate
        converted = self._voice_converter.convert(waveform, self.sample_rate)
        return converted, int(self._voice_converter.sample_rate)

    def _normalize_speech_waveform(self, waveform: Any):
        import numpy as np

        samples = self._waveform_as_numpy(waveform)
        active = np.abs(samples) >= 10 ** (-45 / 20)
        if not active.any():
            return samples
        rms = float(np.sqrt(np.mean(np.square(samples[active]))))
        if rms <= 0:
            return samples
        target = 10 ** (self.loudness_target_dbfs / 20)
        ceiling = 10 ** (self.peak_ceiling_dbfs / 20)
        gain = min(target / rms, ceiling / float(np.max(np.abs(samples))))
        return samples * gain

    async def _synthesize_wav_bytes(
        self, text: str, speaker: str, style: VoiceStyle | str = VoiceStyle.AUTO
    ) -> tuple[bytes, float, int]:
        await self._ensure_model()
        self._validate_speaker(speaker)
        started = time.perf_counter()
        async with self._infer_lock:
            (waveform, output_sample_rate) = await asyncio.wait_for(
                asyncio.to_thread(self._render_sync, text, speaker, style),
                timeout=self.timeout_seconds,
            )
        synthesis_ms = int((time.perf_counter() - started) * 1000)
        wav_bytes = waveform_to_wav_bytes(self._normalize_speech_waveform(waveform), output_sample_rate)
        duration = wav_duration_seconds(wav_bytes)
        logger.info(
            "Silero TTS segment synthesized: provider=silero model=%s speaker=%s device=%s "
            "text_length=%s word_count=%s style=%s voice_conversion=%s synthesis_ms=%s "
            "audio_duration_ms=%s RTF=%.3f audio_bytes=%s",
            self.model_name,
            speaker,
            self._selected_device,
            len(text),
            len(text.split()),
            str(style),
            self._voice_converter is not None,
            synthesis_ms,
            int(duration * 1000),
            (synthesis_ms / 1000) / duration if duration else 0.0,
            len(wav_bytes),
        )
        return wav_bytes, duration, synthesis_ms

    async def stream(self, request: TTSRequest):
        text = " ".join(request.text.strip().split())
        if not text:
            raise ValueError("TTS text is empty")
        speaker = self.resolve_voice(request.language, request.voice)
        style = coerce_voice_style(request.style)
        wav_bytes, _, _ = await self._synthesize_wav_bytes(text, speaker, style)
        yield AudioChunk(
            data=wav_bytes,
            format="wav",
            sequence=0,
            is_final=True,
            metadata={
                "sample_rate": self.metadata["sample_rate"],
                "channels": 1,
                "sample_width": 2,
                "speaker": speaker,
                "model": self.model_name,
                "device": self._selected_device,
                "voice_conversion": self._voice_converter is not None,
                "native_english": self._english_tts_model is not None,
                "style": style.value,
            },
        )

    async def synthesize(
        self, text: str, voice: str, output_path: Path, style: VoiceStyle | str = VoiceStyle.AUTO
    ) -> TTSResult:
        normalized = " ".join(text.strip().split())
        if not normalized:
            raise ValueError("TTS text is empty")
        speaker = self.resolve_voice("ru", voice)
        started = time.perf_counter()
        output_path = output_path.with_suffix(self.file_extension)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
        temp_path.unlink(missing_ok=True)
        try:
            wav_bytes, audio_duration_seconds, _ = await self._synthesize_wav_bytes(normalized, speaker, style)
            temp_path.write_bytes(wav_bytes)
            if wav_duration_seconds(temp_path.read_bytes()) <= 0:
                raise RuntimeError("Silero TTS returned zero-duration audio")
            temp_path.replace(output_path)
        except asyncio.CancelledError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception:
            temp_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            raise
        return TTSResult(
            audio_path=output_path,
            duration_ms=int((time.perf_counter() - started) * 1000),
            provider="silero",
            voice=speaker,
            chunks_count=1,
            audio_duration_seconds=audio_duration_seconds,
        )




def split_tts_chunks(text: str, max_chars: int = 90, max_words: int = 18) -> list[str]:
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
    return _merge_short_tail(chunks, max_chars, max_words) or [normalized]


def _tts_chunk_fits(text: str, max_chars: int, max_words: int) -> bool:
    return len(text) <= max_chars and len(text.split()) <= max_words


def _minimum_tts_duration_seconds(text: str) -> float:
    words = len(text.split())
    chars = len(text)
    if words <= 2 and chars <= 16:
        return 0.15
    estimated_duration = max(0.25, min(words * 0.12, chars * 0.015))
    return estimated_duration * 0.85


def _split_tts_sentence(text: str, max_chars: int, max_words: int) -> list[str]:
    if _tts_chunk_fits(text, max_chars, max_words):
        return [text]
    for pattern in (r"(?<=[;:])\s+", r"(?<=,)\s+"):
        parts = [part.strip() for part in re.split(pattern, text) if part.strip()]
        if len(parts) > 1:
            chunks: list[str] = []
            for part in parts:
                if _tts_chunk_fits(part, max_chars, max_words):
                    chunks.append(part)
                else:
                    chunks.extend(_split_long_tts_text(part, max_chars, max_words))
            return _merge_short_tail(chunks, max_chars, max_words)
    return _split_long_tts_text(text, max_chars, max_words)


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
    return _merge_short_tail(chunks, max_chars, max_words)


def _merge_short_tail(chunks: list[str], max_chars: int, max_words: int) -> list[str]:
    if len(chunks) >= 2 and len(chunks[-1].split()) <= 3:
        candidate = f"{chunks[-2]} {chunks[-1]}"
        if _tts_chunk_fits(candidate, int(max_chars * 1.25), max_words):
            chunks[-2] = candidate
            chunks.pop()
    return chunks
