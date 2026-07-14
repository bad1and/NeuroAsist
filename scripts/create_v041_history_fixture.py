"""Regenerate the deterministic SQLite history fixture inherited from V0.4.1."""

from __future__ import annotations

import sqlite3
from pathlib import Path


FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "v0.4.1-history.sqlite3"
ROWS = (
    ("default", "user", "Привет, Нейро.", "2026-07-13 09:00:00"),
    ("default", "assistant", "Привет! Я на связи.", "2026-07-13 09:00:02"),
    ("voice-demo", "user", "Проверим голос.", "2026-07-13 09:01:00"),
    ("voice-demo", "assistant", "Голосовой цикл готов.", "2026-07-13 09:01:04"),
)


def main() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    if FIXTURE.exists():
        FIXTURE.unlink()

    with sqlite3.connect(FIXTURE) as connection:
        connection.execute("PRAGMA user_version = 0")
        connection.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "CREATE INDEX idx_messages_session_created "
            "ON messages (session_id, created_at, id)"
        )
        connection.executemany(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            ROWS,
        )


if __name__ == "__main__":
    main()
