from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.backend import main as backend_main
from apps.backend.app.core.config import Settings
from apps.backend.app.runtime.settings import RuntimeSettings, RuntimeSettingsStore


class FailingTTSPreloadVoiceService:
    def __init__(self, settings: Settings) -> None:
        self.tts_provider = SimpleNamespace(name=settings.voice_tts_provider)

    def available_tts_voices(self) -> list[str]:
        return ["ru_f1"]

    async def preload_stt(self) -> None:
        return None

    async def preload_tts(self) -> None:
        raise RuntimeError("tts preload failed")

    def clear_tts_audio(self) -> int:
        return 0


def test_startup_replaces_persisted_unknown_voice_with_teratts_default(
    monkeypatch,
    tmp_path,
) -> None:
    settings = Settings(
        deepseek_api_key="test-key",
        app_data_dir=str(tmp_path / "app-data"),
        sqlite_path=str(tmp_path / "startup.sqlite3"),
        log_to_file=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_stt_provider="mock",
        voice_tts_provider="teratts",
        voice_teratts_voice="ru_f1",
    )
    store = RuntimeSettingsStore(settings.app_data_path / "settings.json")
    store.save(RuntimeSettings(voice_tts_voice="aidar"))
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)

    app = backend_main.create_app()

    assert app.state.runtime_settings.voice_tts_voice == "ru_f1"
    assert store.load(RuntimeSettings()).voice_tts_voice == "ru_f1"


def test_startup_migrates_legacy_tts_provider_and_voice_to_ru_f1(
    monkeypatch,
    tmp_path,
) -> None:
    settings = Settings(
        deepseek_api_key="test-key",
        app_data_dir=str(tmp_path / "app-data"),
        sqlite_path=str(tmp_path / "startup.sqlite3"),
        log_to_file=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_stt_provider="mock",
        voice_tts_provider="supertonic",
    )
    store = RuntimeSettingsStore(settings.app_data_path / "settings.json")
    store.save(RuntimeSettings(voice_tts_voice="F4"))
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)

    app = backend_main.create_app()

    assert app.state.runtime_settings.voice_tts_voice == "ru_f1"
    assert store.load(RuntimeSettings()).voice_tts_voice == "ru_f1"


def test_startup_continues_when_tts_preload_fails(
    monkeypatch,
    tmp_path,
) -> None:
    settings = Settings(
        deepseek_api_key="test-key",
        sqlite_path=str(tmp_path / "startup.sqlite3"),
        log_to_file=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=True,
        voice_tts_enabled=True,
        voice_tts_provider="teratts",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)
    monkeypatch.setattr(backend_main, "VoiceService", FailingTTSPreloadVoiceService)

    app = backend_main.create_app()

    with TestClient(app) as client:
        response = client.get("/health")
        events = client.get("/events?limit=20").json()["events"]

    assert response.status_code == 200
    assert any(event["type"] == "voice.tts_preload_failed" for event in events)
    assert any(event["type"] == "backend.status" for event in events)


def test_startup_removes_existing_tts_wavs(monkeypatch, tmp_path) -> None:
    audio_dir = tmp_path / "audio" / "tts"
    audio_dir.mkdir(parents=True)
    (audio_dir / "stale.wav").write_bytes(b"wav")
    settings = Settings(
        deepseek_api_key="test-key",
        sqlite_path=str(tmp_path / "startup.sqlite3"),
        voice_audio_dir=str(tmp_path / "audio"),
        log_to_file=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_stt_provider="mock",
        voice_tts_provider="mock",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)

    with TestClient(backend_main.create_app()):
        pass

    assert not (audio_dir / "stale.wav").exists()
