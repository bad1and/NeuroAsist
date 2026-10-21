import asyncio

from fastapi.testclient import TestClient
from types import SimpleNamespace

from apps.backend import main as backend_main
from apps.backend.app.core.config import Settings


class FailingTtsService:
    def __init__(self, settings: Settings) -> None:
        self.tts_provider = SimpleNamespace(name=settings.voice_tts_provider)

    def available_tts_voices(self) -> list[str]:
        return ["ru_f1"]

    async def preload_tts(self) -> None:
        raise RuntimeError("test tts failure")

    def clear_tts_audio(self) -> int:
        return 0


def test_safe_mode_skips_all_voice_model_initialization_and_finishes_readiness(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from apps.backend.app.model_manager import service as model_service
    monkeypatch.setenv("NEUROASIST_SAFE_MODE", "1")
    settings = Settings(_env_file=None, deepseek_api_key="test-key", app_data_dir=str(tmp_path),
        sqlite_path=str(tmp_path / "safe.sqlite3"), log_to_file=False, avatar_enabled=False,
        voice_preload_stt_model=True, voice_preload_tts_model=True,
        voice_stt_provider="mock", voice_tts_provider="mock", voice_vad_provider="silero",
        semantic_retrieval_enabled=True, semantic_retrieval_eval_passed=True, semantic_embedding_provider="e5")
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)
    configure_torch = Mock(side_effect=AssertionError("Safe Mode must not initialize Torch"))
    require_model = Mock(side_effect=AssertionError("Safe Mode must not load VAD/Smart Turn"))
    load_embedding = Mock(side_effect=AssertionError("Safe Mode must not load embedding weights"))
    monkeypatch.setattr(backend_main, "configure_torch_threads", configure_torch)
    monkeypatch.setattr(model_service, "require_managed_model", require_model)
    monkeypatch.setattr(backend_main, "LocalE5EmbeddingProvider", load_embedding)
    app = backend_main.create_app()
    with TestClient(app) as client:
        async def settle():
            await app.state.voice_preload_task
        client.portal.call(settle)
        readiness = client.get("/readiness").json()
        assert readiness["stt"] == "disabled" and readiness["tts"] == "disabled"
        assert readiness["vad"] == "fallback"
        assert client.get("/health").json()["status"] == "ok"
    configure_torch.assert_not_called()
    require_model.assert_not_called()
    load_embedding.assert_not_called()


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


def test_successful_storage_maintenance_does_not_report_failure(monkeypatch, tmp_path):
    settings = Settings(_env_file=None, app_data_dir=str(tmp_path),
                        sqlite_path=str(tmp_path / "data/neuroasist.sqlite3"),
                        log_to_file=False, avatar_enabled=False, voice_stt_provider="mock",
                        voice_tts_provider="mock", voice_preload_stt_model=False,
                        voice_preload_tts_model=False, voice_vad_provider="energy")
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)
    events = []
    original = backend_main.EventBus.publish
    def capture(bus, event_type, level, message, metadata):
        events.append((event_type, level, message))
        return original(bus, event_type, level, message, metadata)
    monkeypatch.setattr(backend_main.EventBus, "publish", capture)
    with TestClient(backend_main.create_app()) as client:
        async def wait_for_storage():
            await asyncio.wait_for(client.app.state.storage_maintenance_ready.wait(), timeout=10)
        client.portal.call(wait_for_storage)
        assert client.get("/health").json() == {"status": "ok"}
    assert not any("Deferred storage maintenance failed" in message for _, _, message in events)


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
        async def wait_for_voice():
            await asyncio.wait_for(asyncio.shield(client.app.state.voice_preload_task), timeout=10)
        client.portal.call(wait_for_voice)
        readiness = client.get("/readiness").json()

    assert readiness["text_chat"] == "ready"
    assert readiness["tts"] == "failed"
    assert readiness["live_ready"] is False
    assert any(error.startswith("tts:") for error in readiness["errors"])


def test_managed_vad_is_verified_and_becomes_ready(monkeypatch, tmp_path) -> None:
    from pathlib import Path
    from apps.backend.app.voice.input import VadProvider
    verified = []
    settings = Settings(_env_file=None, app_data_dir=str(tmp_path), sqlite_path=str(tmp_path / "data/neuroasist.sqlite3"),
                        log_to_file=False, avatar_enabled=False, voice_stt_provider="mock", voice_tts_provider="mock",
                        voice_preload_stt_model=False, voice_preload_tts_model=False, voice_vad_provider="silero")
    class ReadyVad(VadProvider):
        name = "silero"
        ready = True
        error = None
        def __init__(self, path):
            assert isinstance(path, Path)
    def verify(model_id, path):
        assert isinstance(path, Path)
        verified.append(model_id)
    monkeypatch.setenv("NEUROASIST_MANAGED_MODELS", "1")
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)
    monkeypatch.setattr(backend_main, "SileroVadProvider", ReadyVad)
    monkeypatch.setattr("apps.backend.app.model_manager.service.require_managed_model", verify)
    with TestClient(backend_main.create_app()) as client:
        async def wait_for_voice():
            await asyncio.wait_for(asyncio.shield(client.app.state.voice_preload_task), timeout=10)
        client.portal.call(wait_for_voice)
        readiness = client.get("/readiness").json()
    assert readiness["vad"] == "ready"
    assert "silero-vad" in verified
