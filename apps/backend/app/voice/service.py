import shutil
from collections import OrderedDict
from typing import Any
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from apps.backend.app.core.config import Settings
from apps.backend.app.voice.providers import (
    EdgeTTSProvider,
    FasterWhisperSTTProvider,
    MockSTTProvider,
    MockTTSProvider,
    STTProvider,
    TTSProvider,
)

ALLOWED_AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "application/octet-stream": ".webm",
}


class VoiceService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stt_provider = self._build_stt_provider(settings)
        self._tts_provider = self._build_tts_provider(settings)
        self._tts_jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_tts_jobs = 300

    @property
    def stt_provider(self) -> STTProvider:
        return self._stt_provider

    @property
    def tts_provider(self) -> TTSProvider:
        return self._tts_provider

    async def preload(self) -> None:
        await self._stt_provider.preload()

    def set_tts_job(self, voice_request_id: str, payload: dict[str, Any]) -> None:
        self._tts_jobs[voice_request_id] = {
            "voice_request_id": voice_request_id,
            **payload,
        }
        self._tts_jobs.move_to_end(voice_request_id)
        while len(self._tts_jobs) > self._max_tts_jobs:
            self._tts_jobs.popitem(last=False)

    def get_tts_job(self, voice_request_id: str) -> dict[str, Any] | None:
        job = self._tts_jobs.get(voice_request_id)
        if job is None:
            return None
        self._tts_jobs.move_to_end(voice_request_id)
        return dict(job)

    async def save_upload(self, upload: UploadFile) -> Path:
        content_type = upload.content_type or "application/octet-stream"
        suffix = ALLOWED_AUDIO_TYPES.get(content_type)
        if suffix is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unsupported audio type",
            )

        upload_dir = self._settings.voice_audio_path / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        output_path = upload_dir / f"{uuid4().hex}{suffix}"
        max_bytes = self._settings.voice_max_upload_mb * 1024 * 1024
        written = 0

        with output_path.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    output.close()
                    output_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Audio upload is too large",
                    )
                output.write(chunk)

        await upload.close()
        return output_path

    def next_tts_path(self, provider_name: str) -> Path:
        suffix = ".wav" if provider_name == "mock" else ".mp3"
        output_dir = self._settings.voice_audio_path / "tts"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"{uuid4().hex}{suffix}"

    def resolve_audio_path(self, audio_id: str) -> Path:
        if "/" in audio_id or "\\" in audio_id or ".." in audio_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")

        path = self._settings.voice_audio_path / "tts" / audio_id
        try:
            path.resolve().relative_to((self._settings.voice_audio_path / "tts").resolve())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found") from exc

        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")
        return path

    def cleanup_upload(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def clear_audio_dir(self) -> None:
        root = self._settings.voice_audio_path
        if root.exists():
            shutil.rmtree(root)

    def _build_stt_provider(self, settings: Settings) -> STTProvider:
        if settings.voice_stt_provider == "mock":
            return MockSTTProvider()
        if settings.voice_stt_provider == "faster_whisper":
            return FasterWhisperSTTProvider(
                settings.voice_stt_model,
                settings.voice_stt_device,
                settings.voice_stt_compute_type,
            )
        raise ValueError(f"Unsupported STT provider: {settings.voice_stt_provider}")

    def _build_tts_provider(self, settings: Settings) -> TTSProvider:
        if settings.voice_tts_provider == "mock":
            return MockTTSProvider()
        if settings.voice_tts_provider == "edge_tts":
            return EdgeTTSProvider()
        raise ValueError(f"Unsupported TTS provider: {settings.voice_tts_provider}")
