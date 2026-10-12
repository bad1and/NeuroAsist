import os
import tempfile
from pathlib import Path

os.environ["LOG_TO_FILE"] = "false"
os.environ["VOICE_TTS_PROVIDER"] = "mock"
_TEST_STATE = Path(tempfile.mkdtemp(prefix="neuroasist-tests-"))
os.environ["NEUROASIST_APP_DATA_DIR"] = str(_TEST_STATE)
os.environ["SQLITE_PATH"] = str(_TEST_STATE / "data" / "neuroasist.sqlite3")
os.environ["VOICE_AUDIO_DIR"] = str(_TEST_STATE / "data" / "audio")

import pytest


@pytest.fixture(autouse=True)
def isolated_user_profile(monkeypatch, tmp_path):
    """Every test gets a separate profile, including non-secret persisted preferences."""
    root = tmp_path / "profile"
    monkeypatch.setenv("NEUROASIST_APP_DATA_DIR", str(root))
    monkeypatch.setenv("SQLITE_PATH", str(root / "data/neuroasist.sqlite3"))
    monkeypatch.setenv("VOICE_AUDIO_DIR", str(root / "data/audio"))
    from apps.backend.app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

