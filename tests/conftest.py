import os
import tempfile
from pathlib import Path

os.environ["LOG_TO_FILE"] = "false"
os.environ["VOICE_TTS_PROVIDER"] = "mock"
_TEST_STATE = Path(tempfile.mkdtemp(prefix="neuroasist-tests-"))
os.environ["NEUROASIST_APP_DATA_DIR"] = str(_TEST_STATE)
os.environ["SQLITE_PATH"] = str(_TEST_STATE / "data" / "neuroasist.sqlite3")
os.environ["VOICE_AUDIO_DIR"] = str(_TEST_STATE / "data" / "audio")

