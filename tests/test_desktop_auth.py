from fastapi.testclient import TestClient

from apps.backend import main as backend_main
from apps.backend.app.core.config import Settings


def test_desktop_token_protects_http_routes_but_preserves_dev_mode(monkeypatch, tmp_path) -> None:
    settings = Settings(
        deepseek_api_key="test-key",
        sqlite_path=str(tmp_path / "desktop.sqlite3"),
        desktop_auth_token="desktop-secret",
        log_to_file=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_stt_provider="mock",
        voice_tts_provider="mock",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)

    with TestClient(backend_main.create_app()) as client:
        assert client.get("/health").status_code == 401
        assert client.get("/health", headers={"X-NeuroAsist-Token": "desktop-secret"}).json() == {"status": "ok"}
        assert client.options("/status").status_code in {200, 405}


def test_browser_mode_does_not_require_desktop_token(monkeypatch, tmp_path) -> None:
    settings = Settings(
        deepseek_api_key="test-key",
        sqlite_path=str(tmp_path / "browser.sqlite3"),
        log_to_file=False,
        voice_preload_stt_model=False,
        voice_preload_tts_model=False,
        voice_stt_provider="mock",
        voice_tts_provider="mock",
    )
    monkeypatch.setattr(backend_main, "get_settings", lambda: settings)

    with TestClient(backend_main.create_app()) as client:
        assert client.get("/health").status_code == 200
