import json
import sqlite3
from pathlib import Path

from apps.backend.app.storage.sqlite_history import SQLiteMessageHistory


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "v0.4.1-history.sqlite3"
MANIFEST = ROOT / "Docs" / "version-manifest-v0.4.1.json"


def test_v041_history_fixture_matches_legacy_history_contract(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite3"
    database.write_bytes(FIXTURE.read_bytes())
    history = SQLiteMessageHistory(database)

    history.init_db()

    assert [(message.role, message.content) for message in history.get_recent_messages("default", 20)] == [
        ("user", "Привет, Нейро."),
        ("assistant", "Привет! Я на связи."),
    ]
    assert [(message.role, message.content) for message in history.get_recent_messages("voice-demo", 1)] == [
        ("assistant", "Голосовой цикл готов."),
    ]
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone() == (4,)


def test_v041_manifest_records_tested_compatibility_surface() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["baseline"]["source_branch"] == "v0.4.1"
    assert manifest["baseline"]["source_commit"] == "467919ab5b65ed3405cc2f51f0e8aaf53edb741d"
    assert manifest["runtime"]["avatar_protocol"]["supported_versions"] == [1, 2]
    assert manifest["fixtures"]["v041_history"] == "tests/fixtures/v0.4.1-history.sqlite3"
