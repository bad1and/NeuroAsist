import sqlite3
from pathlib import Path

from apps.backend.app.llm.base import ChatMessage


class SQLiteMessageHistory:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_session_created
                ON messages (session_id, created_at, id)
                """
            )

    def save_message(self, session_id: str, role: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (session_id, role, content)
                VALUES (?, ?, ?)
                """,
                (session_id, role, content),
            )

    def get_recent_messages(self, session_id: str, limit: int) -> list[ChatMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content
                FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

        return [
            ChatMessage(role=row["role"], content=row["content"])
            for row in reversed(rows)
        ]

    def check_health(self) -> bool:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection
