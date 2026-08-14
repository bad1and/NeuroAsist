from fastapi.testclient import TestClient
from types import SimpleNamespace

from apps.backend import main as backend_main
from apps.backend.app.core.config import Settings


class FailingTtsService:
    def __init__(self, settings: Settings) -> None:
        self.tts_provider = SimpleNamespace(name=settings.voice_tts_provider)

    def available_tts_voices(self) -> list[str]:
        return ["xenia"]

    async def preload_tts(self) -> None:
        raise RuntimeError("test tts failure")

    def clear_tts_audio(self) -> int:
        return 0


def test_readiness_keeps_text_available_when_voice_is_disabled(monkeypatch, tmp_path) -> None:
    settings = Settings(
        deepseek_api_key="test-key",
        app_data_dir=str(tmp_path / "app-data"),
        sqlite_path=str(tmp_path / "readiness.sqlite3"),
        log_to_file=False,
        avatar_enabled=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_tts_enabled=False,
        voice_stt_provider="mock",
        voice_tts_provider="mock",
        voice_vad_provider="energy",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)

    with TestClient(backend_main.create_app()) as client:
        readiness = client.get("/readiness").json()
        health = client.get("/health").json()

    assert health == {"status": "ok"}
    assert readiness["text_chat"] == "ready"
    assert readiness["stt"] == "disabled"
    assert readiness["tts"] == "disabled"
    assert readiness["live_ready"] is False


def test_readiness_degrades_voice_without_blocking_text(monkeypatch, tmp_path) -> None:
    settings = Settings(
        deepseek_api_key="test-key",
        app_data_dir=str(tmp_path / "app-data"),
        sqlite_path=str(tmp_path / "readiness.sqlite3"),
        log_to_file=False,
        avatar_enabled=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=True,
        voice_tts_enabled=True,
        voice_stt_provider="mock",
        voice_tts_provider="mock",
        voice_vad_provider="energy",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)
    monkeypatch.setattr(backend_main, "VoiceService", FailingTtsService)

    with TestClient(backend_main.create_app()) as client:
        readiness = client.get("/readiness").json()

    assert readiness["text_chat"] == "ready"
    assert readiness["tts"] == "failed"
    assert readiness["live_ready"] is False
    assert any(error.startswith("tts:") for error in readiness["errors"])
