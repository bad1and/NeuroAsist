from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.backend.app.api.routes.documents import router as documents_router
from apps.backend.app.api.routes.voice import router as voice_router
from apps.backend.app.documents import DocumentService
from apps.backend.app.storage.timeline import TimelineStore


def test_new_http_stack_spools_document_and_serves_audio_ranges(tmp_path):
    store = TimelineStore(tmp_path / "timeline.sqlite3")
    store.init_db()
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF0123456789WAVE")
    app = FastAPI()
    app.state.timeline_store = store
    app.state.document_service = DocumentService()
    app.state.voice_service = SimpleNamespace(resolve_audio_path=lambda _: audio)
    app.include_router(documents_router)
    app.include_router(voice_router)
    with TestClient(app) as client:
        # Cross the multipart in-memory threshold and exercise disk spooling
        # through Iris's real document route, rather than a framework-only echo.
        content = (b"release note\n" * 100_000)
        uploaded = client.post("/documents", data={"session_id": "qa", "upload_id": "11111111-1111-1111-1111-111111111111"},
                               files={"file": ("release.md", content)})
        # Extraction has its own 150000-character limit; parsing must still
        # reach Iris's explicit error and leave no active attachment.
        assert uploaded.status_code == 422
        assert "150" in uploaded.text
        assert client.get("/documents/current?session_id=qa").json()["document"] is None
        valid = client.post("/documents", data={"session_id": "qa", "upload_id": "22222222-2222-2222-2222-222222222222"},
                            files={"file": ("release.md", b"A readable document")})
        assert valid.status_code == 200, valid.text
        ranged = client.get("/voice/audio/sample", headers={"Range": "bytes=0-3"})
        assert ranged.status_code == 206
        assert ranged.content == b"RIFF"
        assert ranged.headers["content-range"] == f"bytes 0-3/{audio.stat().st_size}"
        malformed = client.get("/voice/audio/sample", headers={"Range": "bytes=invalid"})
        assert malformed.status_code == 400
        assert client.get("/voice/audio/sample", headers={"Range": "bytes=999-1000"}).status_code == 416
        # A bounded overlap set exercises the formerly quadratic merging path.
        overlap = client.get("/voice/audio/sample", headers={"Range": "bytes=" + ",".join(["0-3"] * 200)})
        assert overlap.status_code == 206 and overlap.content == b"RIFF"
