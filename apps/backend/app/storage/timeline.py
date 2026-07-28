"""Versioned SQLite storage for the single V0.5 companion timeline."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from apps.backend.app.llm.base import ChatMessage


PRIMARY_RELATIONSHIP_ID = "primary"
PRIMARY_TIMELINE_ID = "primary-timeline"
LATEST_SCHEMA_VERSION = 13


@dataclass(frozen=True)
class EpisodePolicy:
    enabled: bool = True
    soft_inactivity_seconds: int = 20 * 60
    hard_inactivity_seconds: int = 60 * 60
    maximum_messages: int = 120
    maximum_tokens: int = 16000


@dataclass(frozen=True)
class StoredTimelineMessage:
    id: str
    timeline_id: str
    session_id: str | None
    episode_id: str | None
    role: str
    content: str
    corrected_content: str | None
    client_message_id: str | None
    utterance_id: str | None
    generation: int | None
    sequence_no: int
    turn_id: str | None
    reply_to_message_id: str | None
    status: str
    input_mode: str
    language: str | None
    created_at: str
    completed_at: str | None
    cancelled_at: str | None
    metadata: dict[str, object]

    @property
    def effective_content(self) -> str:
        return self.corrected_content or self.content

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "timeline_id": self.timeline_id,
            "session_id": self.session_id,
            "episode_id": self.episode_id,
            "role": self.role,
            "content": self.effective_content,
            "original_content": self.content,
            "corrected_content": self.corrected_content,
            "client_message_id": self.client_message_id,
            "utterance_id": self.utterance_id,
            "generation": self.generation,
            "sequence_no": self.sequence_no,
            "turn_id": self.turn_id,
            "reply_to_message_id": self.reply_to_message_id,
            "status": self.status,
            "input_mode": self.input_mode,
            "language": self.language,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "cancelled_at": self.cancelled_at,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class AcceptedTimelineTurn:
    """The durable result of accepting a user input."""

    message: StoredTimelineMessage
    generation: int
    created: bool


@dataclass(frozen=True)
class AssistantTimelineLease:
    message: StoredTimelineMessage
    created: bool


class TimelineStore:
    """Canonical V0.5 store with a minimal in-process migration runner."""

    def __init__(
        self,
        db_path: Path,
        episode_policy: EpisodePolicy | None = None,
        event_publisher: Callable[[str, str, str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._db_path = db_path
        self._episode_policy = episode_policy or EpisodePolicy()
        self._event_publisher = event_publisher

    def init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            if 1 not in applied:
                self._apply_v1(connection)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)",
                    (self._now(),),
                )
            if 2 not in applied:
                self._apply_v2(connection)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (2, ?)",
                    (self._now(),),
                )
            if 3 not in applied:
                self._apply_v3(connection)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (3, ?)", (self._now(),))
            if 4 not in applied:
                self._apply_v4(connection)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (4, ?)", (self._now(),))
            if 5 not in applied:
                self._apply_v5(connection)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (5, ?)", (self._now(),))
            if 6 not in applied:
                self._apply_live_conversation_schema(connection)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (6, ?)", (self._now(),))
            # Migration number 6 was already used by some released databases
            # before the live-conversation tables were introduced. Version 10
            # is an idempotent repair migration for those installations.
            if 10 not in applied:
                self._apply_live_conversation_schema(connection)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (10, ?)",
                    (self._now(),),
                )
            if 11 not in applied:
                self._apply_v11_memory_schema(connection)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (11, ?)", (self._now(),))
            if 12 not in applied:
                self._apply_v12_continuity_schema(connection)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (12, ?)", (self._now(),))
            if 13 not in applied:
                self._apply_v13_session_schema(connection)
                connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (13, ?)", (self._now(),))
            # v12 reached some development databases before all of its
            # additive objects existed.  Keep this repair idempotent and run
            # it even when the migration marker is already present.
            self._apply_v12_continuity_schema(connection)
            self._apply_v13_session_schema(connection)
            self._ensure_primary_timeline(connection)
            self._migrate_legacy_messages(connection)
            # Legacy V0.4 rows are imported after migrations, so backfill their
            # new physical session_id column once the import has completed.
            self._apply_v13_session_schema(connection)
            self._backfill_continuity(connection)
            self._assign_unassigned_messages_to_import_episode(connection)
            self._rebuild_timeline_fts(connection)
            self._queue_unsummarized_closed_episodes(connection)

    def append_message(
        self,
        *,
        role: str,
        content: str,
        input_mode: str,
        status: str = "completed",
        client_message_id: str | None = None,
        utterance_id: str | None = None,
        generation: int | None = None,
        turn_id: str | None = None,
        reply_to_message_id: str | None = None,
        language: str | None = None,
        corrected_content: str | None = None,
        metadata: dict[str, object] | None = None,
        session_id: str | None = None,
        created_at: str | None = None,
    ) -> tuple[StoredTimelineMessage, bool]:
        if role not in {"user", "assistant", "system_event"}:
            raise ValueError("Unsupported timeline message role")
        if input_mode not in {"voice", "text", "system"}:
            raise ValueError("Unsupported timeline input mode")
        if status not in {"pending", "accepted", "streaming", "completed", "cancelled", "interrupted", "failed"}:
            raise ValueError("Unsupported timeline message status")
        if not content.strip():
            raise ValueError("Timeline message content cannot be empty")

        with self._connect() as connection:
            session_id = session_id or self._active_session_id(connection) or "default"
            if client_message_id:
                existing = connection.execute(
                    "SELECT * FROM conversation_messages WHERE timeline_id = ? AND session_id IS ? AND client_message_id = ?",
                    (PRIMARY_TIMELINE_ID, session_id, client_message_id),
                ).fetchone()
                if existing is not None:
                    return self._row_to_message(existing), False
            now = created_at or self._now()
            episode_id = self._ensure_active_episode(connection, now, content) if self._episode_policy.enabled else None
            message_id = uuid4().hex
            # Wall-clock timestamps collide under bursty voice/text input.  A
            # monotonically assigned sequence is the canonical causal order.
            sequence_no = int(connection.execute(
                "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM conversation_messages WHERE timeline_id = ?",
                (PRIMARY_TIMELINE_ID,),
            ).fetchone()[0])
            if role == "user" and turn_id is None:
                turn_id = uuid4().hex
            completed_at = now if status == "completed" else None
            try:
                connection.execute(
                    """
                    INSERT INTO conversation_messages (
                        id, timeline_id, session_id, episode_id, role, content, corrected_content, client_message_id,
                        utterance_id, generation, sequence_no, turn_id, reply_to_message_id,
                        status, input_mode, language, created_at, completed_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id, PRIMARY_TIMELINE_ID, session_id, episode_id, role, content, corrected_content,
                        client_message_id, utterance_id, generation, sequence_no, turn_id, reply_to_message_id,
                        status, input_mode, language, now, completed_at, json.dumps(metadata or {}, ensure_ascii=False),
                    ),
                )
            except sqlite3.IntegrityError:
                if client_message_id is None:
                    raise
                existing = connection.execute(
                    "SELECT * FROM conversation_messages WHERE timeline_id = ? AND client_message_id = ?",
                    (PRIMARY_TIMELINE_ID, client_message_id),
                ).fetchone()
                if existing is None:
                    raise
                return self._row_to_message(existing), False
            self._touch_timeline(connection, message_id, now)
            if episode_id is not None:
                self._touch_episode(connection, episode_id, content, now)
            if role == "assistant" and status == "completed" and episode_id is not None:
                self._refresh_continuity_checkpoint(connection, episode_id, sequence_no)
            self._index_timeline_message(connection, message_id, content)
            row = connection.execute("SELECT * FROM conversation_messages WHERE id = ?", (message_id,)).fetchone()
        return self._row_to_message(row), True

    def accept_user_turn(
        self,
        *,
        session_key: str,
        content: str,
        input_mode: str,
        client_message_id: str | None = None,
        utterance_id: str | None = None,
        language: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AcceptedTimelineTurn:
        """Persist a user turn before any generation can be cancelled.

        This is intentionally a single ``BEGIN IMMEDIATE`` transaction.  It
        makes sequence allocation, durable generation allocation and client-id
        de-duplication one causal operation even when a text and voice request
        arrive concurrently.
        """
        if not content.strip():
            raise ValueError("Timeline message content cannot be empty")
        if input_mode not in {"voice", "text", "system"}:
            raise ValueError("Unsupported timeline input mode")
        with self._immediate_connect() as connection:
            active_session_id = self._active_session_id(connection)
            if active_session_id is not None and session_key != active_session_id:
                raise ValueError("Session is no longer active")
            if client_message_id:
                existing = connection.execute(
                    "SELECT * FROM conversation_messages WHERE timeline_id = ? AND session_id IS ? AND client_message_id = ?",
                    (PRIMARY_TIMELINE_ID, session_key, client_message_id),
                ).fetchone()
                if existing is not None:
                    message = self._row_to_message(existing)
                    if message.role != "user" or message.content != content or message.input_mode != input_mode:
                        raise ValueError("client_message_id is already bound to different content")
                    return AcceptedTimelineTurn(message, int(message.generation or 0), False)

            state = connection.execute(
                "SELECT generation FROM conversation_turn_state WHERE timeline_id = ? AND session_key = ?",
                (PRIMARY_TIMELINE_ID, session_key),
            ).fetchone()
            previous_generation = int(state["generation"]) if state is not None else 0
            generation = previous_generation + 1
            now = self._now()
            episode_id = self._ensure_active_episode(connection, now, content) if self._episode_policy.enabled else None
            sequence_no = self._next_sequence(connection)
            message_id, turn_id = uuid4().hex, uuid4().hex
            payload = {"legacy_session_id": session_key, **(metadata or {})}
            connection.execute(
                """INSERT INTO conversation_messages (
                    id, timeline_id, session_id, episode_id, role, content, client_message_id, utterance_id,
                    generation, sequence_no, turn_id, status, input_mode, language, created_at,
                    completed_at, metadata_json
                ) VALUES (?, ?, ?, ?, 'user', ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?)""",
                (
                    message_id, PRIMARY_TIMELINE_ID, session_key, episode_id, content, client_message_id, utterance_id,
                    generation, sequence_no, turn_id, input_mode, language, now, now,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            connection.execute(
                """INSERT INTO conversation_turn_state
                   (timeline_id, session_key, generation, active_turn_id, active_user_message_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(timeline_id, session_key) DO UPDATE SET generation = excluded.generation,
                     active_turn_id = excluded.active_turn_id,
                     active_user_message_id = excluded.active_user_message_id, updated_at = excluded.updated_at""",
                (PRIMARY_TIMELINE_ID, session_key, generation, turn_id, message_id, now),
            )
            self._touch_timeline(connection, message_id, now)
            if episode_id is not None:
                self._touch_episode(connection, episode_id, content, now)
            self._index_timeline_message(connection, message_id, content)
            row = connection.execute("SELECT * FROM conversation_messages WHERE id = ?", (message_id,)).fetchone()
            return AcceptedTimelineTurn(self._row_to_message(row), generation, True)

    def begin_assistant_turn(
        self, *, session_key: str, user_message_id: str, generation: int, utterance_id: str | None = None,
        input_mode: str = "text", metadata: dict[str, object] | None = None,
    ) -> AssistantTimelineLease:
        """Reserve the stable assistant id before the first streamed token."""
        with self._immediate_connect() as connection:
            user = connection.execute(
                "SELECT * FROM conversation_messages WHERE id = ? AND timeline_id = ? AND session_id = ? AND role = 'user'",
                (user_message_id, PRIMARY_TIMELINE_ID, session_key),
            ).fetchone()
            if user is None:
                raise KeyError(user_message_id)
            existing = connection.execute(
                "SELECT * FROM conversation_messages WHERE role = 'assistant' AND reply_to_message_id = ?",
                (user_message_id,),
            ).fetchone()
            if existing is not None:
                return AssistantTimelineLease(self._row_to_message(existing), False)
            state = connection.execute(
                "SELECT generation, active_user_message_id FROM conversation_turn_state WHERE timeline_id = ? AND session_key = ?",
                (PRIMARY_TIMELINE_ID, session_key),
            ).fetchone()
            if state is None or int(state["generation"]) != generation or state["active_user_message_id"] != user_message_id:
                raise RuntimeError("Cannot begin assistant for a stale generation")
            now, message_id = self._now(), uuid4().hex
            sequence_no = self._next_sequence(connection)
            connection.execute(
                """INSERT INTO conversation_messages (
                    id, timeline_id, session_id, episode_id, role, content, utterance_id, generation, sequence_no,
                    turn_id, reply_to_message_id, status, input_mode, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, 'assistant', '', ?, ?, ?, ?, ?, 'streaming', ?, ?, ?)""",
                (
                    message_id, PRIMARY_TIMELINE_ID, session_key, user["episode_id"], utterance_id, generation,
                    sequence_no, user["turn_id"], user_message_id, input_mode, now,
                    json.dumps({"legacy_session_id": session_key, **(metadata or {})}, ensure_ascii=False),
                ),
            )
            row = connection.execute("SELECT * FROM conversation_messages WHERE id = ?", (message_id,)).fetchone()
            return AssistantTimelineLease(self._row_to_message(row), True)

    def finish_assistant_turn(
        self,
        *,
        session_key: str,
        assistant_message_id: str,
        generation: int,
        content: str = "",
        status: str = "completed",
    ) -> StoredTimelineMessage:
        """Apply a terminal assistant state without ever changing its user turn."""
        if status not in {"completed", "interrupted", "failed"}:
            raise ValueError("Assistant terminal status is invalid")
        if status == "completed" and not content.strip():
            raise ValueError("A completed assistant message requires content")
        with self._immediate_connect() as connection:
            assistant = connection.execute(
                "SELECT * FROM conversation_messages WHERE id = ? AND timeline_id = ? AND role = 'assistant'",
                (assistant_message_id, PRIMARY_TIMELINE_ID),
            ).fetchone()
            if assistant is None:
                raise KeyError(assistant_message_id)
            if int(assistant["generation"] or 0) != generation:
                return self._row_to_message(assistant)
            # A later accepted turn may already have closed this lease.  Never
            # let a late provider completion resurrect it as a normal reply.
            if assistant["status"] != "streaming":
                return self._row_to_message(assistant)
            now = self._now()
            terminal_at = now if status == "completed" else None
            cancelled_at = now if status in {"interrupted", "failed"} else None
            connection.execute(
                """UPDATE conversation_messages SET content = ?, status = ?, completed_at = ?, cancelled_at = ?
                   WHERE id = ?""",
                (content, status, terminal_at, cancelled_at, assistant_message_id),
            )
            if content.strip() and status in {"completed", "interrupted"}:
                self._index_timeline_message(connection, assistant_message_id, content)
            if status == "completed" and assistant["episode_id"] is not None:
                self._touch_episode(connection, assistant["episode_id"], content, now)
                self._refresh_continuity_checkpoint(connection, assistant["episode_id"], int(assistant["sequence_no"]))
            connection.execute(
                """UPDATE conversation_turn_state SET active_turn_id = NULL, active_user_message_id = NULL, updated_at = ?
                   WHERE timeline_id = ? AND session_key = ? AND generation = ?
                     AND active_user_message_id = ?""",
                (now, PRIMARY_TIMELINE_ID, session_key, generation, assistant["reply_to_message_id"]),
            )
            row = connection.execute("SELECT * FROM conversation_messages WHERE id = ?", (assistant_message_id,)).fetchone()
            return self._row_to_message(row)

    def assistant_for_user(self, user_message_id: str) -> StoredTimelineMessage | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_messages WHERE role = 'assistant' AND reply_to_message_id = ?",
                (user_message_id,),
            ).fetchone()
        return self._row_to_message(row) if row is not None else None

    def interrupt_stale_assistant_leases(self, *, session_key: str, generation: int) -> list[str]:
        """Close durable leases left between reservation and task registration.

        The coordinator normally has an in-memory task to cancel too, but this
        closes the small crash/race window where a later accepted turn arrives
        after a lease commit and before that task is registered.
        """
        with self._immediate_connect() as connection:
            rows = connection.execute(
                """SELECT id FROM conversation_messages
                   WHERE timeline_id = ? AND role = 'assistant' AND status = 'streaming'
                     AND generation < ? AND session_id = ?""",
                (PRIMARY_TIMELINE_ID, generation, session_key),
            ).fetchall()
            if not rows:
                return []
            now = self._now()
            ids = [str(row["id"]) for row in rows]
            connection.executemany(
                "UPDATE conversation_messages SET status = 'interrupted', cancelled_at = ? WHERE id = ?",
                [(now, message_id) for message_id in ids],
            )
            return ids

    def get_recent_messages(self, session_id: str, limit: int) -> list[ChatMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, corrected_content FROM conversation_messages
                WHERE timeline_id = ? AND session_id = ? AND status = 'completed' AND role IN ('user', 'assistant')
                ORDER BY sequence_no DESC LIMIT ?
                """,
                (PRIMARY_TIMELINE_ID, session_id, limit),
            ).fetchall()
        return [ChatMessage(role=row["role"], content=row["corrected_content"] or row["content"]) for row in reversed(rows)]

    def list_messages(self, limit: int, offset: int = 0) -> tuple[list[StoredTimelineMessage], int | None]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_messages WHERE timeline_id = ? ORDER BY sequence_no DESC LIMIT ? OFFSET ?",
                (PRIMARY_TIMELINE_ID, limit + 1, offset),
            ).fetchall()
        next_offset = offset + limit if len(rows) > limit else None
        return [self._row_to_message(row) for row in reversed(rows[:limit])], next_offset

    def search_messages(self, query: str, limit: int) -> list[StoredTimelineMessage]:
        escaped = query.strip().replace("%", r"\%").replace("_", r"\_")
        with self._connect() as connection:
            fts_query = self._fts_query(query)
            if fts_query:
                rows = connection.execute(
                    """SELECT m.* FROM timeline_message_fts f JOIN conversation_messages m ON m.id = f.message_id
                       WHERE timeline_message_fts MATCH ? AND m.timeline_id = ? ORDER BY bm25(timeline_message_fts), m.sequence_no DESC LIMIT ?""",
                    (fts_query, PRIMARY_TIMELINE_ID, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM conversation_messages
                    WHERE timeline_id = ? AND (content LIKE ? ESCAPE '\\' OR corrected_content LIKE ? ESCAPE '\\')
                    ORDER BY sequence_no DESC LIMIT ?""",
                    (PRIMARY_TIMELINE_ID, f"%{escaped}%", f"%{escaped}%", limit),
                ).fetchall()
        return [self._row_to_message(row) for row in reversed(rows)]

    def correct_message(self, message_id: str, corrected_content: str) -> StoredTimelineMessage:
        if not corrected_content.strip():
            raise ValueError("Corrected content cannot be empty")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_messages WHERE id = ? AND timeline_id = ?",
                (message_id, PRIMARY_TIMELINE_ID),
            ).fetchone()
            if row is None:
                raise KeyError(message_id)
            metadata = json.loads(row["metadata_json"])
            metadata["correction_pending_review"] = True
            connection.execute(
                "UPDATE conversation_messages SET corrected_content = ?, metadata_json = ? WHERE id = ?",
                (corrected_content, json.dumps(metadata, ensure_ascii=False), message_id),
            )
            self._index_timeline_message(connection, message_id, corrected_content)
            return self._row_to_message(connection.execute("SELECT * FROM conversation_messages WHERE id = ?", (message_id,)).fetchone())

    def apply_voice_interpretation(
        self, message_id: str, corrected_content: str, replacement_count: int,
    ) -> StoredTimelineMessage:
        """Store an automatic STT interpretation without overwriting raw audio text."""
        if not corrected_content.strip() or replacement_count < 1:
            raise ValueError("Voice interpretation requires a changed non-empty value")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_messages WHERE id = ? AND timeline_id = ?",
                (message_id, PRIMARY_TIMELINE_ID),
            ).fetchone()
            if row is None:
                raise KeyError(message_id)
            if row["role"] != "user" or row["input_mode"] != "voice":
                raise ValueError("Voice interpretation is only valid for user voice messages")
            metadata = json.loads(row["metadata_json"])
            metadata["voice_interpretation"] = {
                "version": "v1",
                "replacement_count": replacement_count,
            }
            connection.execute(
                "UPDATE conversation_messages SET corrected_content = ?, metadata_json = ? WHERE id = ?",
                (corrected_content, json.dumps(metadata, ensure_ascii=False), message_id),
            )
            self._index_timeline_message(connection, message_id, corrected_content)
            updated = connection.execute("SELECT * FROM conversation_messages WHERE id = ?", (message_id,)).fetchone()
            return self._row_to_message(updated)

    def cancel_message(self, message_id: str) -> StoredTimelineMessage:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM conversation_messages WHERE id = ? AND timeline_id = ?", (message_id, PRIMARY_TIMELINE_ID)).fetchone()
            if row is None:
                raise KeyError(message_id)
            now = self._now()
            connection.execute("UPDATE conversation_messages SET status = 'cancelled', cancelled_at = ? WHERE id = ?", (now, message_id))
            return self._row_to_message(connection.execute("SELECT * FROM conversation_messages WHERE id = ?", (message_id,)).fetchone())

    def delete_range(self, before: str | None, after: str | None) -> int:
        if before is None and after is None:
            raise ValueError("At least one range boundary is required")
        clauses = ["timeline_id = ?"]
        params: list[object] = [PRIMARY_TIMELINE_ID]
        if before is not None:
            clauses.append("created_at <= ?")
            params.append(before)
        if after is not None:
            clauses.append("created_at >= ?")
            params.append(after)
        with self._connect() as connection:
            episode_rows = connection.execute(
                f"SELECT DISTINCT episode_id FROM conversation_messages WHERE {' AND '.join(clauses)} AND episode_id IS NOT NULL",
                params,
            ).fetchall()
            cursor = connection.execute(f"DELETE FROM conversation_messages WHERE {' AND '.join(clauses)}", params)
            for row in episode_rows:
                self._recalculate_episode(connection, row["episode_id"])
            current = connection.execute("SELECT current_episode_id FROM conversation_timelines WHERE id = ?", (PRIMARY_TIMELINE_ID,)).fetchone()
            if current and current["current_episode_id"] is not None:
                exists = connection.execute("SELECT 1 FROM conversation_episodes WHERE id = ?", (current["current_episode_id"],)).fetchone()
                if exists is None:
                    connection.execute("UPDATE conversation_timelines SET current_episode_id = NULL WHERE id = ?", (PRIMARY_TIMELINE_ID,))
            return cursor.rowcount

    def journal(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, status, started_at, last_activity_at, ended_at, boundary_reason,
                       title, message_count, token_estimate, summary_status, summary_version
                FROM conversation_episodes WHERE timeline_id = ?
                ORDER BY started_at DESC, id DESC
                """,
                (PRIMARY_TIMELINE_ID,),
            ).fetchall()
        return [{**dict(row), "day": row["started_at"][:10]} for row in rows]

    def list_episodes(self, limit: int = 100) -> list[dict[str, object]]:
        return self.journal()[:limit]

    def get_episode(self, episode_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_episodes WHERE id = ? AND timeline_id = ?",
                (episode_id, PRIMARY_TIMELINE_ID),
            ).fetchone()
        return dict(row) if row is not None else None

    def delete_episode(self, episode_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM conversation_episodes WHERE id = ? AND timeline_id = ?",
                (episode_id, PRIMARY_TIMELINE_ID),
            ).fetchone()
            if row is None:
                raise KeyError(episode_id)
            deleted = connection.execute("DELETE FROM conversation_messages WHERE episode_id = ?", (episode_id,)).rowcount
            connection.execute("DELETE FROM conversation_episodes WHERE id = ?", (episode_id,))
            connection.execute(
                "UPDATE conversation_timelines SET current_episode_id = NULL WHERE id = ? AND current_episode_id = ?",
                (PRIMARY_TIMELINE_ID, episode_id),
            )
            return deleted

    def current_episode(self) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT e.* FROM conversation_episodes e
                JOIN conversation_timelines t ON t.current_episode_id = e.id
                WHERE t.id = ?
                """,
                (PRIMARY_TIMELINE_ID,),
            ).fetchone()
        return dict(row) if row is not None else None

    def close_current_episode(self, reason: str = "manual_reset", now: str | None = None) -> dict[str, object] | None:
        with self._connect() as connection:
            episode = self._current_episode_row(connection)
            if episode is None:
                return None
            self._close_episode(connection, episode, reason, now or self._now())
            row = connection.execute("SELECT * FROM conversation_episodes WHERE id = ?", (episode["id"],)).fetchone()
            return dict(row)

    def recover_active_episode(self, now: str | None = None) -> dict[str, object] | None:
        """Close only stale active episodes; a restart never creates an empty one."""
        if not self._episode_policy.enabled:
            return None
        current_time = now or self._now()
        with self._connect() as connection:
            episode = self._current_episode_row(connection)
            if episode is None:
                return None
            gap = self._seconds_between(episode["last_activity_at"], current_time)
            if gap >= self._episode_policy.hard_inactivity_seconds:
                self._close_episode(connection, episode, "application_restart", current_time)
                row = connection.execute("SELECT * FROM conversation_episodes WHERE id = ?", (episode["id"],)).fetchone()
                return dict(row)
        return None

    def claim_summary_job(self) -> dict[str, object] | None:
        return self._claim_job("episode_summary")

    def enqueue_memory_index_job(self, memory_id: str) -> None:
        """Durably coalesce Chroma updates; SQLite remains the source of truth."""
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE background_jobs SET status = 'completed' WHERE type = 'memory_index' AND status = 'pending' AND json_extract(payload_json, '$.memory_id') = ?",
                (memory_id,),
            )
            connection.execute(
                """INSERT INTO background_jobs (id, type, status, payload_json, idempotency_key, available_at, created_at, updated_at)
                   VALUES (?, 'memory_index', 'pending', ?, ?, ?, ?, ?)
                   ON CONFLICT(type, idempotency_key) WHERE idempotency_key IS NOT NULL DO UPDATE SET
                     status = 'pending', payload_json = excluded.payload_json, available_at = excluded.available_at,
                     updated_at = excluded.updated_at, lease_owner = NULL, lease_until = NULL""",
                (uuid4().hex, json.dumps({"memory_id": memory_id}), f"memory-index:{memory_id}", now, now, now),
            )

    def enqueue_memory_extraction_job(self, message_id: str) -> None:
        """Queue one durable DeepSeek extraction pass for a user turn.

        A turn is allowed to produce only one pending extraction job. Repeated
        scheduling can happen when a caller retries after a transient error,
        so older pending copies are completed before enqueueing the newest one.
        """
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO background_jobs (id, type, status, payload_json, idempotency_key, available_at, created_at, updated_at)
                   VALUES (?, 'memory_extract', 'pending', ?, ?, ?, ?, ?)
                   ON CONFLICT(type, idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING""",
                (uuid4().hex, json.dumps({"message_id": message_id, "pipeline_version": "v11"}), f"memory-extract:{message_id}:v11", now, now, now),
            )

    def enqueue_consolidation_job(self, end_message_id: str, *, pipeline_version: str = "v11") -> None:
        """Coalesce a dialogue window by its relationship, terminal message and pipeline version."""
        now, key = self._now(), f"consolidation:{PRIMARY_RELATIONSHIP_ID}:{end_message_id}:{pipeline_version}"
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO background_jobs (id, type, status, payload_json, idempotency_key, available_at, created_at, updated_at)
                   VALUES (?, 'memory_consolidation', 'pending', ?, ?, ?, ?, ?)
                   ON CONFLICT(type, idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING""",
                (uuid4().hex, json.dumps({"end_message_id": end_message_id, "pipeline_version": pipeline_version}), key, now, now, now),
            )

    def claim_memory_extraction_job(self) -> dict[str, object] | None:
        return self._claim_job("memory_extract") or self._claim_job("memory_consolidation")

    def claim_memory_index_job(self) -> dict[str, object] | None:
        return self._claim_job("memory_index")

    def recover_memory_index_jobs(self) -> None:
        """A process crash may leave a claimed job running; make it retry on startup."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE background_jobs SET status = 'pending', available_at = ?, updated_at = ?, lease_owner = NULL, lease_until = NULL WHERE type IN ('memory_index', 'memory_extract', 'memory_consolidation') AND status = 'running' AND (lease_until IS NULL OR lease_until <= ?)",
                (self._now(), self._now(), self._now()),
            )

    def complete_summary_job(self, job_id: str) -> None:
        with self._connect() as connection:
            now = self._now()
            connection.execute("UPDATE background_jobs SET status = 'completed', completed_at = ?, updated_at = ?, lease_owner = NULL, lease_until = NULL WHERE id = ?", (now, now, job_id))

    def fail_summary_job(self, job_id: str, error: str) -> None:
        with self._connect() as connection:
            job = connection.execute("SELECT attempts FROM background_jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                return
            now = datetime.now(UTC)
            if job["attempts"] < 3:
                delay_seconds = 2 ** job["attempts"]
                connection.execute(
                    "UPDATE background_jobs SET status = 'pending', available_at = ?, error_text = ?, updated_at = ?, lease_owner = NULL, lease_until = NULL WHERE id = ?",
                    ((now + timedelta(seconds=delay_seconds)).isoformat(timespec="milliseconds"), error[:500], now.isoformat(timespec="milliseconds"), job_id),
                )
            else:
                connection.execute("UPDATE background_jobs SET status = 'failed', error_text = ?, updated_at = ? WHERE id = ?", (error[:500], now.isoformat(timespec="milliseconds"), job_id))

    def _claim_job(self, job_type: str, lease_seconds: int = 120) -> dict[str, object] | None:
        """Atomically claim one ready or expired job with a renewable SQLite lease."""
        now = datetime.now(UTC)
        now_text = now.isoformat(timespec="milliseconds")
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="milliseconds")
        owner = uuid4().hex
        with self._connect() as connection:
            row = connection.execute(
                """UPDATE background_jobs
                   SET status = 'running', attempts = attempts + 1, lease_owner = ?, lease_until = ?, updated_at = ?
                   WHERE id = (
                     SELECT id FROM background_jobs
                     WHERE type = ? AND available_at <= ?
                       AND (status = 'pending' OR (status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?))
                     ORDER BY available_at, created_at LIMIT 1
                   )
                   AND (status = 'pending' OR (status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?))
                   RETURNING *""",
                (owner, lease_until, now_text, job_type, now_text, now_text, now_text),
            ).fetchone()
        return dict(row) if row is not None else None

    def summarize_episode(self, episode_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            episode = connection.execute("SELECT * FROM conversation_episodes WHERE id = ?", (episode_id,)).fetchone()
            if episode is None or episode["message_count"] == 0:
                return None
            rows = connection.execute(
                """
                SELECT m.id, m.role, m.content, m.corrected_content,
                       o.decision_action, o.decision_reason, o.speaker_role
                FROM conversation_messages m
                LEFT JOIN conversation_observations o ON o.message_id = m.id
                WHERE m.episode_id = ?
                ORDER BY m.created_at, m.id
                """,
                (episode_id,),
            ).fetchall()
            user_texts = [
                (row["corrected_content"] or row["content"]).strip()
                for row in rows
                if row["role"] == "user"
                and row["decision_action"] not in {
                    "observe", "avatar_reaction", "defer", "wait_more"
                }
            ]
            ambient_texts = [
                (row["corrected_content"] or row["content"]).strip()
                for row in rows
                if row["role"] == "user"
                and row["decision_action"] in {"observe", "avatar_reaction", "defer"}
            ]
            decisions = [text for text in user_texts if any(marker in text.lower() for marker in ("решил", "решили", "нужно", "не делать", "будем"))][:5]
            open_loops = [text for text in user_texts if "?" in text][-3:]
            topics = self._keywords(" ".join(user_texts))[:5]
            direct_summary = " ".join(user_texts[:1] + user_texts[-1:]).strip()
            ambient_summary = " ".join(ambient_texts[-2:]).strip()
            summary_parts = []
            if direct_summary:
                summary_parts.append(f"Прямой диалог с Iris: {direct_summary}")
            if ambient_summary:
                summary_parts.append(
                    "Фоновая речь, услышанная Iris, но адресованная не ей: "
                    f"{ambient_summary}"
                )
            summary_text = " ".join(summary_parts)[:900] or "Conversation episode"
            version = connection.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM episode_summaries WHERE episode_id = ?", (episode_id,)).fetchone()[0]
            now = self._now()
            connection.execute("UPDATE episode_summaries SET superseded_at = ? WHERE episode_id = ? AND superseded_at IS NULL", (now, episode_id))
            summary_id = uuid4().hex
            connection.execute("""INSERT INTO episode_summaries (id, episode_id, version, summary_text, topics_json, decisions_json, open_loops_json, source_message_ids_json, prompt_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'deterministic-v2-address-aware', ?)""", (summary_id, episode_id, version, summary_text, json.dumps(topics, ensure_ascii=False), json.dumps(decisions, ensure_ascii=False), json.dumps(open_loops, ensure_ascii=False), json.dumps([row["id"] for row in rows]), now))
            connection.execute("INSERT INTO episode_summary_fts (summary_id, text) VALUES (?, ?)", (summary_id, summary_text))
            connection.execute("UPDATE conversation_episodes SET summary_status = 'summarized', summary_version = ? WHERE id = ?", (version, episode_id))
            return {"id": summary_id, "episode_id": episode_id, "summary_text": summary_text, "topics": topics, "decisions": decisions, "open_loops": open_loops}

    def get_message(self, message_id: str) -> StoredTimelineMessage | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM conversation_messages WHERE id = ? AND timeline_id = ?", (message_id, PRIMARY_TIMELINE_ID)).fetchone()
        return self._row_to_message(row) if row is not None else None

    def message_for_utterance(self, utterance_id: str, *, role: str = "user") -> StoredTimelineMessage | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM conversation_messages WHERE timeline_id = ?
                   AND utterance_id = ? AND role = ? ORDER BY sequence_no DESC LIMIT 1""",
                (PRIMARY_TIMELINE_ID, utterance_id, role),
            ).fetchone()
        return self._row_to_message(row) if row is not None else None

    def memory_extraction_context(self, message_id: str, limit: int = 4) -> list[StoredTimelineMessage]:
        """Return the target user turn and a small amount of prior dialogue.

        The boundary is the target message itself, rather than "latest now", so
        a delayed background job cannot use a later turn as evidence.
        """
        with self._connect() as connection:
            target = connection.execute(
                "SELECT created_at, id FROM conversation_messages WHERE id = ? AND timeline_id = ?",
                (message_id, PRIMARY_TIMELINE_ID),
            ).fetchone()
            if target is None:
                return []
            rows = connection.execute(
                """SELECT * FROM conversation_messages
                   WHERE timeline_id = ? AND status = 'completed' AND role IN ('user', 'assistant')
                     AND NOT (
                         role = 'user'
                         AND COALESCE(json_extract(metadata_json, '$.dialogue_scope'), '')
                             IN ('ambient', 'incomplete')
                     )
                   AND sequence_no <= (SELECT sequence_no FROM conversation_messages WHERE id = ?)
                   ORDER BY sequence_no DESC LIMIT ?""",
                (PRIMARY_TIMELINE_ID, message_id, max(1, limit)),
            ).fetchall()
        return [self._row_to_message(row) for row in reversed(rows)]

    def list_memories(self, *, status: str | None = None, query: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        with self._connect() as connection:
            if query and self._fts_query(query):
                rows = connection.execute(
                    """SELECT m.* FROM memory_fts f JOIN memory_items m ON m.id = f.memory_id
                       WHERE memory_fts MATCH ? AND (? IS NULL OR m.status = ?)
                       ORDER BY bm25(memory_fts), m.importance DESC, m.updated_at DESC LIMIT ?""",
                    (self._fts_query(query), status, status, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM memory_items WHERE relationship_id = ? AND (? IS NULL OR status = ?) ORDER BY importance DESC, updated_at DESC LIMIT ?",
                    (PRIMARY_RELATIONSHIP_ID, status, status, limit),
                ).fetchall()
        return [self._memory_row(row) for row in rows]

    def create_memory(self, values: dict[str, object], *, actor: str, action: str = "candidate_created") -> dict[str, object]:
        now = self._now()
        memory_id = uuid4().hex
        source_ids = list(values.get("source_message_ids", []))
        source_episode_id = values.get("source_episode_id")
        canonical = str(values.get("canonical_text") or f"{values['subject']} {values['predicate']} {values['value_text']}")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO memory_items (
                    id, relationship_id, scope, kind, subject, predicate, value_text, canonical_text,
                    importance, confidence, sensitivity, status, user_locked, valid_from, valid_to, expires_at,
                    source_episode_id, source_message_ids_json, extractor_version, supersedes_id, superseded_by_id,
                    created_at, updated_at, last_accessed_at, access_count, metadata_json,
                    extraction_model, cardinality, temporal_semantics, source_quality, claim_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, 0, '{}', ?, ?, ?, ?, ?)""",
                (memory_id, PRIMARY_RELATIONSHIP_ID, values["scope"], values["kind"], values["subject"], values["predicate"],
                 values["value_text"], canonical, values.get("importance", 0.5), values.get("confidence", 0.5),
                 values.get("sensitivity", "normal"), values.get("status", "candidate"), int(bool(values.get("user_locked", False))),
                 values.get("valid_from"), values.get("valid_to"), values.get("expires_at"), source_episode_id,
                 json.dumps(source_ids, ensure_ascii=False), values.get("extractor_version", "memory-v1"), now, now,
                 values.get("extraction_model"), values.get("cardinality", "multi"), values.get("temporal_semantics", "atemporal"),
                 values.get("source_quality", 1.0), values.get("claim_fingerprint")),
            )
            self._index_memory(connection, memory_id, canonical)
            for message_id in source_ids:
                self._add_evidence(connection, "fact", memory_id, str(message_id), source_episode_id,
                                   str(values.get("source_role", "user")), float(values.get("source_quality", 1.0)),
                                   str(values.get("evidence_kind", "assertion")), values.get("stt_confidence"))
            row = connection.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            self._audit_memory(connection, memory_id, action, actor, None, self._memory_row(row), None, source_ids)
            return self._memory_row(row)

    def update_memory(self, memory_id: str, changes: dict[str, object], *, actor: str = "user", action: str = "edited") -> dict[str, object]:
        allowed = {"value_text", "importance", "confidence", "user_locked", "expires_at"}
        updates = {key: value for key, value in changes.items() if key in allowed and value is not None}
        if not updates:
            memory = self.get_memory(memory_id)
            if memory is None:
                raise KeyError(memory_id)
            return memory
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                raise KeyError(memory_id)
            before = self._memory_row(row)
            if "value_text" in updates:
                updates["canonical_text"] = f"{row['subject']} {row['predicate']} {updates['value_text']}"
            updates["updated_at"] = self._now()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            connection.execute(f"UPDATE memory_items SET {assignments} WHERE id = ?", (*updates.values(), memory_id))
            row = connection.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            self._index_memory(connection, memory_id, row["canonical_text"])
            after = self._memory_row(row)
            self._audit_memory(connection, memory_id, action, actor, before, after, None, after["source_message_ids"])
            return after

    def get_memory(self, memory_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
        return self._memory_row(row) if row is not None else None

    def memory_evidence(self, entity_type: str, entity_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_evidence WHERE entity_type = ? AND entity_id = ? ORDER BY created_at, id",
                (entity_type, entity_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_topic(self, values: dict[str, object], *, actor: str = "system") -> dict[str, object]:
        now = self._now()
        topic_id = str(values.get("id") or uuid4().hex)
        title, summary = str(values["title"]).strip(), str(values.get("summary_text", "")).strip()
        if not title:
            raise ValueError("Topic title cannot be empty")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO memory_topics (id, relationship_id, title, summary_text, status, user_locked, extractor_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (topic_id, PRIMARY_RELATIONSHIP_ID, title, summary, values.get("status", "active"),
                 int(bool(values.get("user_locked", False))), values.get("extractor_version", "manual-v1"), now, now),
            )
            connection.execute("INSERT INTO memory_topic_versions (id, topic_id, version, title, summary_text, reason, created_at) VALUES (?, ?, 1, ?, ?, ?, ?)",
                               (uuid4().hex, topic_id, title, summary, f"created:{actor}", now))
            self._index_topic(connection, topic_id, f"{title} {summary}")
        return self.get_topic(topic_id) or {}

    def list_topics(self, *, status: str | None = None, query: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        with self._connect() as connection:
            if query and self._fts_query(query):
                rows = connection.execute(
                    """SELECT t.* FROM memory_topic_fts f JOIN memory_topics t ON t.id = f.topic_id
                       WHERE memory_topic_fts MATCH ? AND (? IS NULL OR t.status = ?) ORDER BY bm25(memory_topic_fts), t.updated_at DESC LIMIT ?""",
                    (self._fts_query(query), status, status, limit),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM memory_topics WHERE relationship_id = ? AND (? IS NULL OR status = ?) ORDER BY updated_at DESC LIMIT ?", (PRIMARY_RELATIONSHIP_ID, status, status, limit)).fetchall()
        return [self._topic_row(row) for row in rows]

    def get_topic(self, topic_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memory_topics WHERE id = ?", (topic_id,)).fetchone()
        return self._topic_row(row) if row is not None else None

    def update_topic(self, topic_id: str, changes: dict[str, object], *, actor: str = "user") -> dict[str, object]:
        allowed = {key: value for key, value in changes.items() if key in {"title", "summary_text", "status", "user_locked"} and value is not None}
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memory_topics WHERE id = ?", (topic_id,)).fetchone()
            if row is None:
                raise KeyError(topic_id)
            if not allowed:
                return self._topic_row(row)
            allowed["updated_at"] = self._now()
            connection.execute("UPDATE memory_topics SET " + ", ".join(f"{key} = ?" for key in allowed) + " WHERE id = ?", (*allowed.values(), topic_id))
            updated = connection.execute("SELECT * FROM memory_topics WHERE id = ?", (topic_id,)).fetchone()
            version = connection.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM memory_topic_versions WHERE topic_id = ?", (topic_id,)).fetchone()[0]
            connection.execute("INSERT INTO memory_topic_versions (id, topic_id, version, title, summary_text, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (uuid4().hex, topic_id, version, updated["title"], updated["summary_text"], f"updated:{actor}", self._now()))
            self._index_topic(connection, topic_id, f"{updated['title']} {updated['summary_text']}")
            return self._topic_row(updated)

    def merge_topics(self, survivor_id: str, merged_id: str) -> dict[str, object]:
        if survivor_id == merged_id:
            raise ValueError("A topic cannot be merged into itself")
        with self._connect() as connection:
            survivor = connection.execute("SELECT * FROM memory_topics WHERE id = ?", (survivor_id,)).fetchone()
            merged = connection.execute("SELECT * FROM memory_topics WHERE id = ?", (merged_id,)).fetchone()
            if survivor is None or merged is None:
                raise KeyError("Topic not found")
            now = self._now()
            connection.execute("UPDATE memory_topics SET status = 'merged', merged_into_id = ?, updated_at = ? WHERE id = ?", (survivor_id, now, merged_id))
            connection.execute("INSERT OR IGNORE INTO memory_topic_links (topic_id, entity_type, entity_id, created_at) SELECT ?, entity_type, entity_id, ? FROM memory_topic_links WHERE topic_id = ?", (survivor_id, now, merged_id))
            connection.execute("DELETE FROM memory_topic_fts WHERE topic_id = ?", (merged_id,))
        return self.get_topic(survivor_id) or {}

    def link_topic(self, topic_id: str, entity_type: str, entity_id: str) -> None:
        with self._connect() as connection:
            connection.execute("INSERT OR IGNORE INTO memory_topic_links (topic_id, entity_type, entity_id, created_at) VALUES (?, ?, ?, ?)", (topic_id, entity_type, entity_id, self._now()))

    def create_commitment(self, values: dict[str, object]) -> dict[str, object]:
        now, commitment_id = self._now(), str(values.get("id") or uuid4().hex)
        with self._connect() as connection:
            connection.execute("""INSERT INTO memory_commitments (id, relationship_id, kind, title, details, status, importance, confidence, user_locked, due_at, source_episode_id, extractor_version, created_at, updated_at, completed_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                               (commitment_id, PRIMARY_RELATIONSHIP_ID, values.get("kind", "open_loop"), values["title"], values.get("details", ""), values.get("status", "open"), values.get("importance", .6), values.get("confidence", .7), int(bool(values.get("user_locked", False))), values.get("due_at"), values.get("source_episode_id"), values.get("extractor_version", "manual-v1"), now, now, now if values.get("status") == "completed" else None))
            self._index_commitment(connection, commitment_id, f"{values['title']} {values.get('details', '')}")
            for message_id in values.get("source_message_ids", []):
                self._add_evidence(connection, "commitment", commitment_id, str(message_id), values.get("source_episode_id"), "user", float(values.get("source_quality", 1.0)), "commitment", None)
        return self.get_commitment(commitment_id) or {}

    def list_commitments(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memory_commitments WHERE relationship_id = ? AND (? IS NULL OR status = ?) ORDER BY importance DESC, updated_at DESC LIMIT ?", (PRIMARY_RELATIONSHIP_ID, status, status, limit)).fetchall()
        return [dict(row) | {"user_locked": bool(row["user_locked"]), "evidence": self.memory_evidence("commitment", row["id"])} for row in rows]

    def get_commitment(self, commitment_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memory_commitments WHERE id = ?", (commitment_id,)).fetchone()
        return (dict(row) | {"user_locked": bool(row["user_locked"]), "evidence": self.memory_evidence("commitment", commitment_id)}) if row else None

    def update_commitment(self, commitment_id: str, changes: dict[str, object]) -> dict[str, object]:
        allowed = {key: value for key, value in changes.items() if key in {"title", "details", "status", "importance", "confidence", "user_locked", "due_at"} and value is not None}
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memory_commitments WHERE id = ?", (commitment_id,)).fetchone()
            if row is None:
                raise KeyError(commitment_id)
            if allowed:
                allowed["updated_at"] = self._now()
                if allowed.get("status") == "completed": allowed["completed_at"] = self._now()
                connection.execute("UPDATE memory_commitments SET " + ", ".join(f"{key} = ?" for key in allowed) + " WHERE id = ?", (*allowed.values(), commitment_id))
                row = connection.execute("SELECT * FROM memory_commitments WHERE id = ?", (commitment_id,)).fetchone()
                self._index_commitment(connection, commitment_id, f"{row['title']} {row['details']}")
        return self.get_commitment(commitment_id) or {}

    def list_conflicts(self, status: str | None = None) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memory_conflicts WHERE relationship_id = ? AND (? IS NULL OR status = ?) ORDER BY created_at DESC", (PRIMARY_RELATIONSHIP_ID, status, status)).fetchall()
        return [dict(row) for row in rows]

    def create_conflict(self, values: dict[str, object]) -> dict[str, object]:
        conflict_id = uuid4().hex
        with self._connect() as connection:
            connection.execute("""INSERT INTO memory_conflicts (id, relationship_id, existing_entity_type, existing_entity_id, proposed_entity_type, proposed_entity_id, reason, status, resolution, created_at, resolved_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                               (conflict_id, PRIMARY_RELATIONSHIP_ID, values.get("existing_entity_type"), values.get("existing_entity_id"), values.get("proposed_entity_type"), values.get("proposed_entity_id"), values["reason"], values.get("status", "open"), values.get("resolution"), self._now(), values.get("resolved_at")))
        return next(item for item in self.list_conflicts() if item["id"] == conflict_id)

    def derive_profile(self) -> dict[str, object]:
        facts = self.list_memories(status="active", limit=250)
        relevant = [item for item in facts if item["kind"] in {"identity", "goal", "relationship", "shared_milestone", "decision", "preference"}]
        relevant.sort(key=lambda item: (-float(item["importance"]), -float(item["confidence"]), str(item["updated_at"])))
        return {"facts": relevant[:20], "topics": self.list_topics(status="active", limit=8), "commitments": self.list_commitments(status="open", limit=10)}

    def set_memory_status(self, memory_id: str, status: str, *, actor: str, action: str, reason: str | None = None) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                raise KeyError(memory_id)
            before = self._memory_row(row)
            connection.execute("UPDATE memory_items SET status = ?, updated_at = ? WHERE id = ?", (status, self._now(), memory_id))
            row = connection.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            if status in {"deleted", "rejected"}:
                connection.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            else:
                self._index_memory(connection, memory_id, row["canonical_text"])
            after = self._memory_row(row)
            self._audit_memory(connection, memory_id, action, actor, before, after, reason, after["source_message_ids"])
            return after

    def supersede_memory(self, old_id: str, new_id: str) -> None:
        with self._connect() as connection:
            old = connection.execute("SELECT * FROM memory_items WHERE id = ?", (old_id,)).fetchone()
            new = connection.execute("SELECT * FROM memory_items WHERE id = ?", (new_id,)).fetchone()
            if old is None or new is None:
                return
            before = self._memory_row(old)
            now = self._now()
            connection.execute("UPDATE memory_items SET status = 'superseded', superseded_by_id = ?, updated_at = ? WHERE id = ?", (new_id, now, old_id))
            connection.execute("UPDATE memory_items SET supersedes_id = ?, updated_at = ? WHERE id = ?", (old_id, now, new_id))
            connection.execute("DELETE FROM memory_fts WHERE memory_id = ?", (old_id,))
            after = self._memory_row(connection.execute("SELECT * FROM memory_items WHERE id = ?", (old_id,)).fetchone())
            self._audit_memory(connection, old_id, "superseded", "policy", before, after, f"Superseded by {new_id}", after["source_message_ids"])

    def clear_memories(self, status: str | None = None) -> int:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memory_items WHERE relationship_id = ? AND status != 'deleted' AND (? IS NULL OR status = ?)", (PRIMARY_RELATIONSHIP_ID, status, status)).fetchall()
            now = self._now()
            for row in rows:
                before = self._memory_row(row)
                connection.execute("UPDATE memory_items SET status = 'deleted', updated_at = ? WHERE id = ?", (now, row["id"]))
                connection.execute("DELETE FROM memory_fts WHERE memory_id = ?", (row["id"],))
                after = {**before, "status": "deleted", "updated_at": now}
                self._audit_memory(connection, row["id"], "deleted", "user", before, after, "Memory center clear", before["source_message_ids"])
            return len(rows)

    def reset_companion_data(self) -> dict[str, int]:
        """Irreversibly clear the primary companion's timeline and memory."""
        with self._connect() as connection:
            messages = connection.execute("SELECT COUNT(*) FROM conversation_messages WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,)).fetchone()[0]
            memories = connection.execute("SELECT COUNT(*) FROM memory_items WHERE relationship_id = ? AND status != 'deleted'", (PRIMARY_RELATIONSHIP_ID,)).fetchone()[0]
            episodes = connection.execute("SELECT COUNT(*) FROM conversation_episodes WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,)).fetchone()[0]

            # Desktop data survives branch changes and application upgrades. A database
            # created by a newer memory build can therefore contain optional graph and
            # retrieval tables even when the running core only knows the V0.5 schema.
            # Clear known child tables first so their foreign keys cannot block the
            # canonical timeline reset. Missing optional tables are intentionally skipped
            # to keep the same code compatible with fresh and older installations.
            existing_tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            reset_tables_child_first = (
                "conversation_observations",
                "character_state_events",
                "character_participant_states",
                "character_state_snapshots",
                "memory_usage",
                "memory_evidence",
                "memory_topic_links",
                "memory_topic_versions",
                "memory_topic_fts",
                "memory_topics",
                "memory_commitment_fts",
                "memory_commitments",
                "memory_conflicts",
                "memory_retrieval_runs",
                "memory_operations",
                "graph_edge_evidence",
                "memory_contradictions",
                "graph_audit",
                "graph_nodes_fts",
                "graph_edges",
                "graph_nodes",
                "memory_fts",
                "episode_summary_fts",
                "timeline_message_fts",
                "memory_audit",
                "episode_summaries",
                "semantic_vectors",
                "semantic_index_state",
                "background_jobs",
            )
            connection.execute(
                "UPDATE conversation_timelines SET current_episode_id = NULL, latest_message_id = NULL, active_session_id = NULL, updated_at = ? WHERE id = ?",
                (self._now(), PRIMARY_TIMELINE_ID),
            )
            for table in reset_tables_child_first:
                if table in existing_tables:
                    # Table names come exclusively from the fixed allowlist above.
                    connection.execute(f"DELETE FROM {table}")
            connection.execute("DELETE FROM memory_items WHERE relationship_id = ?", (PRIMARY_RELATIONSHIP_ID,))
            connection.execute("DELETE FROM conversation_messages WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,))
            connection.execute("DELETE FROM conversation_episodes WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,))
            return {"messages": int(messages), "memories": int(memories), "episodes": int(episodes)}

    def reset_session(self) -> dict[str, object]:
        """Delete every durable conversation artifact while preserving long-term memory."""
        with self._immediate_connect() as connection:
            messages = int(connection.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,)
            ).fetchone()[0])
            episodes = int(connection.execute(
                "SELECT COUNT(*) FROM conversation_episodes WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,)
            ).fetchone()[0])
            existing_tables = {str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
            for table in (
                "conversation_observations", "character_state_events", "character_participant_states",
                "character_state_snapshots", "timeline_message_fts", "episode_summary_fts",
                "episode_checkpoints", "episode_summaries", "consolidation_runs", "background_jobs",
            ):
                if table in existing_tables:
                    connection.execute(f"DELETE FROM {table}")
            if "semantic_vectors" in existing_tables:
                connection.execute("DELETE FROM semantic_vectors WHERE namespace = 'episode_summary'")
            if "semantic_index_state" in existing_tables:
                connection.execute("DELETE FROM semantic_index_state WHERE namespace = 'episode_summary'")
            connection.execute("DELETE FROM conversation_turn_state WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,))
            connection.execute("DELETE FROM conversation_messages WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,))
            connection.execute("DELETE FROM conversation_episodes WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,))
            session_id = uuid4().hex
            connection.execute(
                """UPDATE conversation_timelines
                   SET current_episode_id = NULL, latest_message_id = NULL, active_session_id = ?, updated_at = ?
                   WHERE id = ?""",
                (session_id, self._now(), PRIMARY_TIMELINE_ID),
            )
        return {"session_id": session_id, "messages": messages, "episodes": episodes}

    def active_session_id(self) -> str | None:
        with self._connect() as connection:
            return self._active_session_id(connection)

    @staticmethod
    def _active_session_id(connection: sqlite3.Connection) -> str | None:
        row = connection.execute(
            "SELECT active_session_id FROM conversation_timelines WHERE id = ?", (PRIMARY_TIMELINE_ID,)
        ).fetchone()
        return str(row["active_session_id"]) if row is not None and row["active_session_id"] else None

    def memory_audit(self, memory_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memory_audit WHERE memory_id = ? ORDER BY created_at, id", (memory_id,)).fetchall()
        return [{**dict(row), "source_message_ids": json.loads(row["source_message_ids_json"])} for row in rows]

    def record_memory_retrieval(self, memory_id: str) -> None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                return
            before = self._memory_row(row)
            now = self._now()
            connection.execute("UPDATE memory_items SET access_count = access_count + 1, last_accessed_at = ? WHERE id = ?", (now, memory_id))
            after = self._memory_row(connection.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone())
            self._audit_memory(connection, memory_id, "retrieved", "system", before, after, None, after["source_message_ids"])

    def reindex_memories(self) -> int:
        with self._connect() as connection:
            connection.execute("DELETE FROM memory_fts")
            rows = connection.execute("SELECT id, canonical_text FROM memory_items WHERE status IN ('candidate', 'active')").fetchall()
            connection.executemany("INSERT INTO memory_fts (memory_id, text) VALUES (?, ?)", [(row["id"], row["canonical_text"]) for row in rows])
            connection.execute("DELETE FROM memory_topic_fts")
            connection.execute("INSERT INTO memory_topic_fts (topic_id, text) SELECT id, title || ' ' || summary_text FROM memory_topics WHERE status = 'active'")
            connection.execute("DELETE FROM memory_commitment_fts")
            connection.execute("INSERT INTO memory_commitment_fts (commitment_id, text) SELECT id, title || ' ' || details FROM memory_commitments WHERE status = 'open'")
            return len(rows)

    def semantic_index_items(self, namespace: str) -> list[tuple[str, str]]:
        with self._connect() as connection:
            if namespace == "memory":
                rows = connection.execute("SELECT id, canonical_text FROM memory_items WHERE status = 'active'").fetchall()
            elif namespace == "episode_summary":
                rows = connection.execute("SELECT id, summary_text FROM episode_summaries WHERE superseded_at IS NULL").fetchall()
            elif namespace == "topic_memory":
                rows = connection.execute("SELECT id, title || ' ' || summary_text FROM memory_topics WHERE status = 'active'").fetchall()
            elif namespace == "commitment_memory":
                rows = connection.execute("SELECT id, title || ' ' || details FROM memory_commitments WHERE status = 'open'").fetchall()
            else:
                raise ValueError(f"Unsupported semantic namespace: {namespace}")
        return [(row["id"], row[1]) for row in rows]

    def context_material(
        self, user_text: str, recent_turns: int, *, session_id: str | None = None, current_message_id: str | None = None,
    ) -> dict[str, object]:
        with self._connect() as connection:
            active = self._current_episode_row(connection)
            active_id = active["id"] if active else ""
            current_sequence = None
            if current_message_id is not None:
                current = connection.execute(
                    "SELECT sequence_no FROM conversation_messages WHERE id = ? AND timeline_id = ? AND (? IS NULL OR session_id = ?)",
                    (current_message_id, PRIMARY_TIMELINE_ID, session_id, session_id),
                ).fetchone()
                if current is not None:
                    current_sequence = int(current["sequence_no"])
            recent = connection.execute(
                """
                SELECT m.id, m.role, m.content, m.corrected_content, m.input_mode, m.sequence_no,
                       o.decision_action, o.decision_reason, o.speaker_role,
                       o.addressedness
                FROM conversation_messages m
                LEFT JOIN conversation_observations o ON o.message_id = m.id
                WHERE m.timeline_id = ? AND (? IS NULL OR m.session_id = ?) AND m.status = 'completed'
                  AND m.role IN ('user','assistant')
                  AND (? IS NULL OR m.sequence_no < ?)
                ORDER BY m.sequence_no DESC
                LIMIT ?
                """,
                (PRIMARY_TIMELINE_ID, session_id, session_id, current_sequence, current_sequence, recent_turns * 2),
            ).fetchall()
            terms = self._keywords(user_text)
            if terms:
                clauses = " OR ".join("s.summary_text LIKE ?" for _ in terms)
                summaries = connection.execute(f"SELECT s.* FROM episode_summaries s WHERE s.superseded_at IS NULL AND s.episode_id != ? AND ({clauses}) ORDER BY s.created_at DESC LIMIT 2", (active_id, *(f"%{term}%" for term in terms))).fetchall()
            else:
                summaries = []
            if not summaries:
                summaries = connection.execute("SELECT s.* FROM episode_summaries s WHERE s.superseded_at IS NULL AND s.episode_id != ? ORDER BY s.created_at DESC LIMIT 2", (active_id,)).fetchall()
            checkpoint = None
            if active_id:
                recent_floor = min((int(row["sequence_no"] or 0) for row in recent), default=0)
                checkpoint = connection.execute(
                    """SELECT * FROM episode_checkpoints WHERE episode_id = ? AND superseded_at IS NULL
                       AND through_sequence < ?
                       ORDER BY through_sequence DESC LIMIT 1""",
                    (active_id, recent_floor),
                ).fetchone()
            rolling_summary = None
            if active_id:
                active_rows = connection.execute(
                    """
                    SELECT m.role, m.content, m.corrected_content,
                           o.decision_action
                    FROM conversation_messages m
                    LEFT JOIN conversation_observations o ON o.message_id = m.id
                    WHERE m.episode_id = ? AND m.status = 'completed'
                      AND m.role IN ('user','assistant')
                    ORDER BY m.sequence_no
                    """,
                    (active_id,),
                ).fetchall()
                older_rows = active_rows[: max(0, len(active_rows) - recent_turns * 2)]
                if older_rows:
                    # Never splice a first and last user fragment.  It loses
                    # Iris's answer and creates a false, repeated topic.
                    rendered = [
                        f"{row['role']}: {(row['corrected_content'] or row['content']).strip()}"
                        for row in older_rows[-6:]
                        if row["decision_action"] not in {"observe", "avatar_reaction", "defer", "wait_more"}
                    ]
                    rolling_summary = "\n".join(rendered)[:1200] or None
        return {
            "active_episode_id": active_id or None,
            "causal_upper_bound": current_sequence,
            "recent": [dict(row) for row in reversed(recent)],
            "summaries": [dict(row) for row in summaries],
            "rolling_summary": rolling_summary,
            "checkpoint": dict(checkpoint) if checkpoint is not None else None,
        }


    @staticmethod
    def _keywords(text: str) -> list[str]:
        words = [word.strip(".,!?;:()[]{}\"'").lower() for word in text.split()]
        return list(dict.fromkeys(word for word in words if len(word) >= 5))

    def timeline(self) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM conversation_timelines WHERE id = ?", (PRIMARY_TIMELINE_ID,)).fetchone()
            relationship = connection.execute("SELECT * FROM companion_relationships WHERE id = ?", (PRIMARY_RELATIONSHIP_ID,)).fetchone()
        return {"id": row["id"], "relationship_id": row["relationship_id"], "created_at": row["created_at"], "updated_at": row["updated_at"], "latest_message_id": row["latest_message_id"], "relationship": {"id": relationship["id"], "character_id": relationship["character_id"], "user_id": relationship["user_id"]}}

    def check_health(self) -> bool:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return True

    def save_character_state_snapshot(
        self,
        relationship_id: str,
        state: dict[str, object],
        *,
        schema_version: int = 1,
    ) -> None:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO character_state_snapshots (relationship_id, schema_version, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(relationship_id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (relationship_id, schema_version, json.dumps(state, ensure_ascii=False), now),
            )

    def load_character_state_snapshot(self, relationship_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT schema_version, state_json, updated_at FROM character_state_snapshots WHERE relationship_id = ?",
                (relationship_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "schema_version": row["schema_version"],
            "state": json.loads(row["state_json"]),
            "updated_at": row["updated_at"],
        }

    def append_character_state_event(
        self,
        *,
        relationship_id: str,
        participant_key: str | None,
        event_kind: str,
        confidence: float,
        intensity: float,
        cause_message_ids: list[str],
        delta: dict[str, object],
    ) -> str:
        event_id = uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO character_state_events (
                    id, relationship_id, participant_key, event_kind, confidence, intensity,
                    cause_message_ids_json, delta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    relationship_id,
                    participant_key,
                    event_kind,
                    confidence,
                    intensity,
                    json.dumps(cause_message_ids, ensure_ascii=False),
                    json.dumps(delta, ensure_ascii=False),
                    self._now(),
                ),
            )
        return event_id

    def upsert_participant_state(
        self,
        *,
        relationship_id: str,
        participant_key: str,
        role: str,
        facets: dict[str, object],
        evidence_count: int,
    ) -> None:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO character_participant_states (
                    relationship_id, participant_key, role, facets_json, evidence_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(relationship_id, participant_key) DO UPDATE SET
                    role = excluded.role,
                    facets_json = excluded.facets_json,
                    evidence_count = excluded.evidence_count,
                    updated_at = excluded.updated_at
                """,
                (
                    relationship_id,
                    participant_key,
                    role,
                    json.dumps(facets, ensure_ascii=False),
                    evidence_count,
                    now,
                    now,
                ),
            )

    def load_participant_states(self, relationship_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT participant_key, role, facets_json, evidence_count, created_at, updated_at
                FROM character_participant_states
                WHERE relationship_id = ?
                ORDER BY participant_key
                """,
                (relationship_id,),
            ).fetchall()
        return [
            {
                "participant_key": row["participant_key"],
                "role": row["role"],
                "facets": json.loads(row["facets_json"]),
                "evidence_count": row["evidence_count"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save_conversation_observation(
        self,
        *,
        message_id: str,
        session_id: str,
        turn_id: str,
        utterance_id: str,
        generation: int,
        speaker_role: str,
        speaker_confidence: float,
        addressedness: float,
        addressed_confidence: float,
        end_of_turn_confidence: float,
        significance: float,
        metadata: dict[str, object],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_observations (
                    message_id, session_id, turn_id, utterance_id, generation, speaker_role,
                    speaker_confidence, addressedness, addressed_confidence, end_of_turn_confidence,
                    significance, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO NOTHING
                """,
                (
                    message_id,
                    session_id,
                    turn_id,
                    utterance_id,
                    generation,
                    speaker_role,
                    speaker_confidence,
                    addressedness,
                    addressed_confidence,
                    end_of_turn_confidence,
                    significance,
                    json.dumps(metadata, ensure_ascii=False),
                    self._now(),
                ),
            )

    def set_observation_decision(self, message_id: str, action: str, reason: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE conversation_observations
                SET decision_action = ?, decision_reason = ?
                WHERE message_id = ?
                """,
                (action, reason, message_id),
            )
            row = connection.execute(
                "SELECT metadata_json FROM conversation_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is not None:
                metadata = json.loads(row["metadata_json"])
                metadata["conversation_decision"] = {
                    "action": action,
                    "reason": reason,
                }
                if action in {"respond", "backchannel"}:
                    metadata["dialogue_scope"] = "direct"
                elif action == "wait_more":
                    metadata["dialogue_scope"] = "incomplete"
                else:
                    metadata["dialogue_scope"] = "ambient"
                connection.execute(
                    "UPDATE conversation_messages SET metadata_json = ? WHERE id = ?",
                    (json.dumps(metadata, ensure_ascii=False), message_id),
                )

    def recent_conversation_observations(self, session_id: str, limit: int = 20) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversation_observations
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [{**dict(row), "metadata": json.loads(row["metadata_json"])} for row in reversed(rows)]

    def _apply_v1(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS companion_relationships (
                id TEXT PRIMARY KEY, character_id TEXT NOT NULL, user_id TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, first_interaction_at TEXT,
                last_interaction_at TEXT, total_interactions INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS conversation_timelines (
                id TEXT PRIMARY KEY, relationship_id TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, current_episode_id TEXT, latest_message_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id TEXT PRIMARY KEY, timeline_id TEXT NOT NULL, episode_id TEXT, role TEXT NOT NULL,
                content TEXT NOT NULL, client_message_id TEXT, utterance_id TEXT, generation INTEGER,
                status TEXT NOT NULL, input_mode TEXT NOT NULL, language TEXT, created_at TEXT NOT NULL,
                completed_at TEXT, cancelled_at TEXT, corrected_content TEXT,
                legacy_source_id INTEGER UNIQUE, metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(timeline_id, client_message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_timeline_created
                ON conversation_messages (timeline_id, created_at, id);
            """
        )

    def _apply_v2(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversation_episodes (
                id TEXT PRIMARY KEY, timeline_id TEXT NOT NULL, status TEXT NOT NULL,
                started_at TEXT NOT NULL, last_activity_at TEXT NOT NULL, ended_at TEXT,
                boundary_reason TEXT, title TEXT, message_count INTEGER NOT NULL DEFAULT 0,
                token_estimate INTEGER NOT NULL DEFAULT 0, summary_status TEXT NOT NULL DEFAULT 'none',
                summary_version INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_conversation_episodes_timeline_activity
                ON conversation_episodes (timeline_id, last_activity_at, id);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_episode_created
                ON conversation_messages (episode_id, created_at, id);
            """
        )
        self._assign_unassigned_messages_to_import_episode(connection)

    def _assign_unassigned_messages_to_import_episode(self, connection: sqlite3.Connection) -> None:
        unassigned = connection.execute(
            "SELECT id, created_at FROM conversation_messages WHERE timeline_id = ? AND episode_id IS NULL ORDER BY created_at, id",
            (PRIMARY_TIMELINE_ID,),
        ).fetchall()
        if not unassigned:
            return
        episode_id = "migration-legacy"
        started_at = unassigned[0]["created_at"]
        last_activity_at = unassigned[-1]["created_at"]
        connection.execute(
            """
            INSERT OR IGNORE INTO conversation_episodes (
                id, timeline_id, status, started_at, last_activity_at, ended_at,
                boundary_reason, title, message_count, token_estimate
            ) VALUES (?, ?, 'closed', ?, ?, ?, 'recovery', 'Imported V0.4.1 history', ?, ?)
            """,
            (episode_id, PRIMARY_TIMELINE_ID, started_at, last_activity_at, last_activity_at,
             len(unassigned), self._token_estimate_for_rows(connection, [row["id"] for row in unassigned])),
        )
        connection.execute(
            "UPDATE conversation_messages SET episode_id = ? WHERE timeline_id = ? AND episode_id IS NULL",
            (episode_id, PRIMARY_TIMELINE_ID),
        )

    def _apply_v3(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS episode_summaries (
                id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, version INTEGER NOT NULL,
                summary_text TEXT NOT NULL, topics_json TEXT NOT NULL DEFAULT '[]',
                decisions_json TEXT NOT NULL DEFAULT '[]', open_loops_json TEXT NOT NULL DEFAULT '[]',
                emotional_context_json TEXT NOT NULL DEFAULT '{}', referenced_entities_json TEXT NOT NULL DEFAULT '[]',
                source_message_ids_json TEXT NOT NULL DEFAULT '[]', model_id TEXT,
                prompt_version TEXT NOT NULL, created_at TEXT NOT NULL, superseded_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_episode_summaries_version ON episode_summaries (episode_id, version);
            CREATE TABLE IF NOT EXISTS background_jobs (
                id TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, error_text TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_background_jobs_available ON background_jobs (status, available_at);
            """
        )

    def _apply_v4(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY, relationship_id TEXT NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL,
                subject TEXT NOT NULL, predicate TEXT NOT NULL, value_text TEXT NOT NULL, canonical_text TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5, confidence REAL NOT NULL DEFAULT 0.5,
                sensitivity TEXT NOT NULL DEFAULT 'normal', status TEXT NOT NULL DEFAULT 'active',
                user_locked INTEGER NOT NULL DEFAULT 0, valid_from TEXT, valid_to TEXT, expires_at TEXT,
                source_episode_id TEXT, source_message_ids_json TEXT NOT NULL DEFAULT '[]', extractor_version TEXT NOT NULL,
                supersedes_id TEXT, superseded_by_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                last_accessed_at TEXT, access_count INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_memory_items_relationship_status ON memory_items (relationship_id, status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_memory_items_subject_predicate ON memory_items (relationship_id, subject, predicate);
            CREATE TABLE IF NOT EXISTS memory_audit (
                id TEXT PRIMARY KEY, memory_id TEXT, action TEXT NOT NULL, actor TEXT NOT NULL,
                before_json TEXT, after_json TEXT, reason TEXT, source_message_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memory_audit_memory_created ON memory_audit (memory_id, created_at);
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(memory_id UNINDEXED, text, tokenize='unicode61');
            CREATE VIRTUAL TABLE IF NOT EXISTS episode_summary_fts USING fts5(summary_id UNINDEXED, text, tokenize='unicode61');
            CREATE VIRTUAL TABLE IF NOT EXISTS timeline_message_fts USING fts5(message_id UNINDEXED, text, tokenize='unicode61');
            """
        )
        self._rebuild_timeline_fts(connection)

    def _apply_v5(self, connection: sqlite3.Connection) -> None:
        """Rebuildable semantic-index metadata; canonical content remains in normal tables."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS semantic_index_state (
                namespace TEXT PRIMARY KEY, model_id TEXT NOT NULL, dimension INTEGER NOT NULL,
                backend TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS semantic_vectors (
                namespace TEXT NOT NULL, item_id TEXT NOT NULL, model_id TEXT NOT NULL,
                dimension INTEGER NOT NULL, vector_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (namespace, item_id)
            );
            CREATE INDEX IF NOT EXISTS idx_semantic_vectors_namespace_model
                ON semantic_vectors (namespace, model_id, dimension);
            """
        )

    def _apply_v13_session_schema(self, connection: sqlite3.Connection) -> None:
        """Add a durable active-session boundary without rewriting old history."""
        message_columns = {row["name"] for row in connection.execute("PRAGMA table_info(conversation_messages)")}
        if "session_id" not in message_columns:
            connection.execute("ALTER TABLE conversation_messages ADD COLUMN session_id TEXT")
        timeline_columns = {row["name"] for row in connection.execute("PRAGMA table_info(conversation_timelines)")}
        if "active_session_id" not in timeline_columns:
            connection.execute("ALTER TABLE conversation_timelines ADD COLUMN active_session_id TEXT")
        connection.execute(
            """UPDATE conversation_messages
               SET session_id = COALESCE(json_extract(metadata_json, '$.legacy_session_id'), 'legacy')
               WHERE session_id IS NULL"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_messages_session_sequence "
            "ON conversation_messages(session_id, sequence_no)"
        )

    def _apply_v12_continuity_schema(self, connection: sqlite3.Connection) -> None:
        """Make turn order and checkpoint provenance durable without rewriting IDs."""
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(conversation_messages)")}
        for name, declaration in {
            "sequence_no": "INTEGER",
            "turn_id": "TEXT",
            "reply_to_message_id": "TEXT",
        }.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE conversation_messages ADD COLUMN {name} {declaration}")
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_messages_timeline_sequence
                ON conversation_messages(timeline_id, sequence_no);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_turn
                ON conversation_messages(turn_id, sequence_no);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_reply_target
                ON conversation_messages(reply_to_message_id);
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_generation_sequence
                ON conversation_messages(timeline_id, generation, sequence_no);
            CREATE TABLE IF NOT EXISTS conversation_turn_state (
                timeline_id TEXT NOT NULL,
                session_key TEXT NOT NULL,
                generation INTEGER NOT NULL DEFAULT 0,
                active_turn_id TEXT,
                active_user_message_id TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (timeline_id, session_key)
            );
            CREATE TABLE IF NOT EXISTS episode_checkpoints (
                id TEXT PRIMARY KEY,
                episode_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                through_sequence INTEGER NOT NULL,
                topic_text TEXT NOT NULL DEFAULT '',
                summary_text TEXT NOT NULL,
                decisions_json TEXT NOT NULL DEFAULT '[]',
                open_questions_json TEXT NOT NULL DEFAULT '[]',
                source_message_ids_json TEXT NOT NULL,
                input_message_ids_json TEXT NOT NULL DEFAULT '[]',
                prompt_version TEXT,
                model_id TEXT,
                created_at TEXT NOT NULL,
                superseded_at TEXT,
                UNIQUE(episode_id, through_sequence)
            );
            CREATE INDEX IF NOT EXISTS idx_episode_checkpoints_current
                ON episode_checkpoints(episode_id, through_sequence DESC);
            CREATE TABLE IF NOT EXISTS consolidation_runs (
                idempotency_key TEXT PRIMARY KEY,
                relationship_id TEXT,
                episode_id TEXT,
                start_sequence INTEGER,
                through_sequence INTEGER,
                end_message_id TEXT NOT NULL,
                pipeline_version TEXT,
                source_message_ids_json TEXT,
                status TEXT NOT NULL,
                result_json TEXT,
                section_errors_json TEXT,
                created_at TEXT,
                applied_at TEXT NOT NULL
            );
            """
        )
        # ALTER is required for already-created v12 development databases.
        checkpoint_columns = {row["name"] for row in connection.execute("PRAGMA table_info(episode_checkpoints)")}
        for name, declaration in {
            "version": "INTEGER NOT NULL DEFAULT 1",
            "input_message_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "prompt_version": "TEXT",
            "model_id": "TEXT",
        }.items():
            if name not in checkpoint_columns:
                connection.execute(f"ALTER TABLE episode_checkpoints ADD COLUMN {name} {declaration}")
        run_columns = {row["name"] for row in connection.execute("PRAGMA table_info(consolidation_runs)")}
        for name, declaration in {
            "relationship_id": "TEXT",
            "episode_id": "TEXT",
            "start_sequence": "INTEGER",
            "through_sequence": "INTEGER",
            "pipeline_version": "TEXT",
            "source_message_ids_json": "TEXT",
            "section_errors_json": "TEXT",
            "created_at": "TEXT",
        }.items():
            if name not in run_columns:
                connection.execute(f"ALTER TABLE consolidation_runs ADD COLUMN {name} {declaration}")
        duplicate = connection.execute(
            """SELECT reply_to_message_id FROM conversation_messages
               WHERE role = 'assistant' AND reply_to_message_id IS NOT NULL
               GROUP BY reply_to_message_id HAVING COUNT(*) > 1 LIMIT 1"""
        ).fetchone()
        if duplicate is None:
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_assistant_reply_lease
                   ON conversation_messages(reply_to_message_id)
                   WHERE role = 'assistant' AND reply_to_message_id IS NOT NULL"""
            )

    def _apply_v11_memory_schema(self, connection: sqlite3.Connection) -> None:
        """Add the v11 canonical memory graph without rewriting old records.

        SQLite installations are upgraded in place, including databases created
        by releases which predate some of the optional memory tables.  The old
        JSON provenance remains authoritative for backwards compatibility and
        is copied into ``memory_evidence`` as a queryable projection.
        """
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(memory_items)")}
        additions = {
            "extraction_model": "TEXT",
            "cardinality": "TEXT NOT NULL DEFAULT 'multi'",
            "temporal_semantics": "TEXT NOT NULL DEFAULT 'atemporal'",
            "source_quality": "REAL NOT NULL DEFAULT 1.0",
            "claim_fingerprint": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE memory_items ADD COLUMN {name} {declaration}")
        job_columns = {row["name"] for row in connection.execute("PRAGMA table_info(background_jobs)")}
        for name, declaration in {
            "idempotency_key": "TEXT",
            "lease_owner": "TEXT",
            "lease_until": "TEXT",
            "completed_at": "TEXT",
            "result_json": "TEXT",
        }.items():
            if name not in job_columns:
                connection.execute(f"ALTER TABLE background_jobs ADD COLUMN {name} {declaration}")
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_background_jobs_type_idempotency
                ON background_jobs(type, idempotency_key) WHERE idempotency_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_background_jobs_lease
                ON background_jobs(status, lease_until);

            CREATE TABLE IF NOT EXISTS memory_evidence (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                message_id TEXT,
                episode_id TEXT,
                source_role TEXT NOT NULL DEFAULT 'user',
                source_quality REAL NOT NULL DEFAULT 1.0,
                evidence_kind TEXT NOT NULL DEFAULT 'assertion',
                stt_confidence REAL,
                created_at TEXT NOT NULL,
                UNIQUE(entity_type, entity_id, message_id, episode_id, evidence_kind)
            );
            CREATE INDEX IF NOT EXISTS idx_memory_evidence_entity ON memory_evidence(entity_type, entity_id);

            CREATE TABLE IF NOT EXISTS memory_topics (
                id TEXT PRIMARY KEY,
                relationship_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                user_locked INTEGER NOT NULL DEFAULT 0,
                merged_into_id TEXT,
                superseded_by_id TEXT,
                extractor_version TEXT NOT NULL DEFAULT 'memory-v11',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memory_topics_relationship_status ON memory_topics(relationship_id, status, updated_at);
            CREATE TABLE IF NOT EXISTS memory_topic_versions (
                id TEXT PRIMARY KEY,
                topic_id TEXT NOT NULL REFERENCES memory_topics(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                title TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(topic_id, version)
            );
            CREATE TABLE IF NOT EXISTS memory_topic_links (
                topic_id TEXT NOT NULL REFERENCES memory_topics(id) ON DELETE CASCADE,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(topic_id, entity_type, entity_id)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_topic_fts USING fts5(topic_id UNINDEXED, text, tokenize='unicode61');

            CREATE TABLE IF NOT EXISTS memory_commitments (
                id TEXT PRIMARY KEY,
                relationship_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                importance REAL NOT NULL DEFAULT 0.6,
                confidence REAL NOT NULL DEFAULT 0.7,
                user_locked INTEGER NOT NULL DEFAULT 0,
                due_at TEXT,
                source_episode_id TEXT,
                extractor_version TEXT NOT NULL DEFAULT 'memory-v11',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_memory_commitments_relationship_status ON memory_commitments(relationship_id, status, updated_at);
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_commitment_fts USING fts5(commitment_id UNINDEXED, text, tokenize='unicode61');

            CREATE TABLE IF NOT EXISTS memory_conflicts (
                id TEXT PRIMARY KEY,
                relationship_id TEXT NOT NULL,
                existing_entity_type TEXT,
                existing_entity_id TEXT,
                proposed_entity_type TEXT,
                proposed_entity_id TEXT,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                resolution TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_memory_conflicts_relationship_status ON memory_conflicts(relationship_id, status, created_at);
            """
        )
        # Backfill is deliberately INSERT OR IGNORE: re-running a partially
        # completed migration neither duplicates evidence nor rewrites audit.
        for row in connection.execute("SELECT id, source_episode_id, source_message_ids_json FROM memory_items"):
            try:
                source_ids = json.loads(row["source_message_ids_json"] or "[]")
            except json.JSONDecodeError:
                source_ids = []
            for message_id in source_ids:
                connection.execute(
                    """INSERT OR IGNORE INTO memory_evidence
                       (id, entity_type, entity_id, message_id, episode_id, source_role, source_quality, evidence_kind, created_at)
                       VALUES (?, 'fact', ?, ?, ?, 'user', 1.0, 'legacy_provenance', ?)""",
                    (uuid4().hex, row["id"], str(message_id), row["source_episode_id"], self._now()),
                )

    def _apply_live_conversation_schema(self, connection: sqlite3.Connection) -> None:
        """Additive live-conversation state and provenance tables."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS character_state_snapshots (
                relationship_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS character_state_events (
                id TEXT PRIMARY KEY,
                relationship_id TEXT NOT NULL,
                participant_key TEXT,
                event_kind TEXT NOT NULL,
                confidence REAL NOT NULL,
                intensity REAL NOT NULL,
                cause_message_ids_json TEXT NOT NULL,
                delta_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_character_state_events_relationship_created
                ON character_state_events (relationship_id, created_at);
            CREATE TABLE IF NOT EXISTS character_participant_states (
                relationship_id TEXT NOT NULL,
                participant_key TEXT NOT NULL,
                role TEXT NOT NULL,
                facets_json TEXT NOT NULL,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (relationship_id, participant_key)
            );
            CREATE TABLE IF NOT EXISTS conversation_observations (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                utterance_id TEXT NOT NULL,
                generation INTEGER NOT NULL,
                speaker_role TEXT NOT NULL,
                speaker_confidence REAL NOT NULL,
                addressedness REAL NOT NULL,
                addressed_confidence REAL NOT NULL,
                end_of_turn_confidence REAL NOT NULL,
                significance REAL NOT NULL,
                decision_action TEXT,
                decision_reason TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conversation_observations_session_created
                ON conversation_observations (session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_conversation_observations_turn
                ON conversation_observations (turn_id);
            """
        )

    @staticmethod
    def _rebuild_timeline_fts(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM episode_summary_fts")
        connection.execute("INSERT INTO episode_summary_fts (summary_id, text) SELECT id, summary_text FROM episode_summaries WHERE superseded_at IS NULL")
        connection.execute("DELETE FROM timeline_message_fts")
        connection.execute("INSERT INTO timeline_message_fts (message_id, text) SELECT id, COALESCE(corrected_content, content) FROM conversation_messages")

    @staticmethod
    def _fts_query(text: str) -> str:
        # SQLite FTS treats `-`, `:`, quotes, and several other characters as
        # query syntax. User text must therefore be tokenized before building
        # a prefix query; otherwise `какую-нибудь` is parsed as a column query.
        terms = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        return " OR ".join(f'"{term}"*' for term in terms if len(term) >= 2)

    @staticmethod
    def _memory_row(row: sqlite3.Row) -> dict[str, object]:
        value = dict(row)
        value["user_locked"] = bool(value["user_locked"])
        value["source_message_ids"] = json.loads(value.pop("source_message_ids_json"))
        value["metadata"] = json.loads(value.pop("metadata_json"))
        return value

    def _audit_memory(
        self, connection: sqlite3.Connection, memory_id: str, action: str, actor: str,
        before: dict[str, object] | None, after: dict[str, object] | None,
        reason: str | None, source_ids: list[str],
    ) -> None:
        connection.execute(
            "INSERT INTO memory_audit (id, memory_id, action, actor, before_json, after_json, reason, source_message_ids_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid4().hex, memory_id, action, actor,
             json.dumps(before, ensure_ascii=False) if before is not None else None,
             json.dumps(after, ensure_ascii=False) if after is not None else None,
             reason, json.dumps(source_ids, ensure_ascii=False), self._now()),
        )

    @staticmethod
    def _index_memory(connection: sqlite3.Connection, memory_id: str, text: str) -> None:
        connection.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        connection.execute("INSERT INTO memory_fts (memory_id, text) VALUES (?, ?)", (memory_id, text))

    @staticmethod
    def _index_topic(connection: sqlite3.Connection, topic_id: str, text: str) -> None:
        connection.execute("DELETE FROM memory_topic_fts WHERE topic_id = ?", (topic_id,))
        connection.execute("INSERT INTO memory_topic_fts (topic_id, text) VALUES (?, ?)", (topic_id, text))

    @staticmethod
    def _index_commitment(connection: sqlite3.Connection, commitment_id: str, text: str) -> None:
        connection.execute("DELETE FROM memory_commitment_fts WHERE commitment_id = ?", (commitment_id,))
        connection.execute("INSERT INTO memory_commitment_fts (commitment_id, text) VALUES (?, ?)", (commitment_id, text))

    def _add_evidence(
        self, connection: sqlite3.Connection, entity_type: str, entity_id: str,
        message_id: str | None, episode_id: object, source_role: str,
        source_quality: float, evidence_kind: str, stt_confidence: object,
    ) -> None:
        connection.execute(
            """INSERT OR IGNORE INTO memory_evidence
               (id, entity_type, entity_id, message_id, episode_id, source_role, source_quality, evidence_kind, stt_confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid4().hex, entity_type, entity_id, message_id, str(episode_id) if episode_id else None,
             source_role, max(0.0, min(1.0, source_quality)), evidence_kind,
             float(stt_confidence) if stt_confidence is not None else None, self._now()),
        )

    def _topic_row(self, row: sqlite3.Row) -> dict[str, object]:
        with self._connect() as connection:
            links = connection.execute("SELECT entity_type, entity_id FROM memory_topic_links WHERE topic_id = ?", (row["id"],)).fetchall()
            versions = connection.execute("SELECT id, version, title, summary_text, reason, created_at FROM memory_topic_versions WHERE topic_id = ? ORDER BY version DESC", (row["id"],)).fetchall()
        result = dict(row)
        result["user_locked"] = bool(result["user_locked"])
        result["links"] = [dict(link) for link in links]
        result["versions"] = [dict(version) for version in versions]
        result["evidence"] = self.memory_evidence("topic", str(row["id"]))
        return result

    @staticmethod
    def _index_timeline_message(connection: sqlite3.Connection, message_id: str, text: str) -> None:
        connection.execute("DELETE FROM timeline_message_fts WHERE message_id = ?", (message_id,))
        connection.execute("INSERT INTO timeline_message_fts (message_id, text) VALUES (?, ?)", (message_id, text))

    def _queue_unsummarized_closed_episodes(self, connection: sqlite3.Connection) -> None:
        """Queue one resilient summary job for closed episodes, including migrated V0.4 history."""
        rows = connection.execute(
            """SELECT id FROM conversation_episodes
               WHERE status = 'closed' AND message_count > 0 AND summary_status = 'none'
               AND NOT EXISTS (
                   SELECT 1 FROM background_jobs
                   WHERE type = 'episode_summary'
                     AND json_extract(payload_json, '$.episode_id') = conversation_episodes.id
               )"""
        ).fetchall()
        now = self._now()
        for row in rows:
            connection.execute(
                "INSERT INTO background_jobs (id, type, status, payload_json, available_at, created_at, updated_at) VALUES (?, 'episode_summary', 'pending', ?, ?, ?, ?)",
                (uuid4().hex, json.dumps({"episode_id": row["id"]}), now, now, now),
            )

    def _ensure_active_episode(self, connection: sqlite3.Connection, now: str, content: str) -> str:
        episode = self._current_episode_row(connection)
        if episode is not None:
            gap = self._seconds_between(episode["last_activity_at"], now)
            if self._should_close_for_time(episode, now, gap):
                reason = "calendar_boundary" if self._day(episode["last_activity_at"]) != self._day(now) else "inactivity"
                self._close_episode(connection, episode, reason, now)
                episode = None
            elif (
                episode["message_count"] >= self._episode_policy.maximum_messages
                or episode["token_estimate"] + self._estimate_tokens(content) > self._episode_policy.maximum_tokens
            ):
                self._close_episode(connection, episode, "context_pressure", now)
                episode = None
        if episode is not None:
            return episode["id"]
        return self._start_episode(connection, now)

    def _start_episode(self, connection: sqlite3.Connection, now: str) -> str:
        episode_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO conversation_episodes (id, timeline_id, status, started_at, last_activity_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            (episode_id, PRIMARY_TIMELINE_ID, now, now),
        )
        connection.execute(
            "UPDATE conversation_timelines SET current_episode_id = ?, updated_at = ? WHERE id = ?",
            (episode_id, now, PRIMARY_TIMELINE_ID),
        )
        self._publish_episode("episode.started", "info", "Conversation episode started", episode_id, None)
        return episode_id

    def _close_episode(self, connection: sqlite3.Connection, episode: sqlite3.Row, reason: str, now: str) -> None:
        if episode["message_count"] == 0:
            connection.execute("DELETE FROM conversation_episodes WHERE id = ?", (episode["id"],))
        else:
            connection.execute(
                """
                UPDATE conversation_episodes
                SET status = 'closed', ended_at = ?, last_activity_at = ?, boundary_reason = ?
                WHERE id = ?
                """,
                (now, episode["last_activity_at"], reason, episode["id"]),
            )
            connection.execute(
                "INSERT INTO background_jobs (id, type, status, payload_json, available_at, created_at, updated_at) VALUES (?, 'episode_summary', 'pending', ?, ?, ?, ?)",
                (uuid4().hex, json.dumps({"episode_id": episode["id"]}), now, now, now),
            )
        connection.execute(
            "UPDATE conversation_timelines SET current_episode_id = NULL, updated_at = ? WHERE id = ?",
            (now, PRIMARY_TIMELINE_ID),
        )
        self._publish_episode("episode.closed", "info", "Conversation episode closed", episode["id"], reason)

    def _touch_episode(self, connection: sqlite3.Connection, episode_id: str, content: str, now: str) -> None:
        connection.execute(
            """
            UPDATE conversation_episodes
            SET last_activity_at = ?, message_count = message_count + 1,
                token_estimate = token_estimate + ?
            WHERE id = ?
            """,
            (now, self._estimate_tokens(content), episode_id),
        )

    def _recalculate_episode(self, connection: sqlite3.Connection, episode_id: str) -> None:
        row = connection.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM((length(content) + 3) / 4), 0) AS tokens, MIN(created_at) AS started_at, MAX(created_at) AS last_activity_at FROM conversation_messages WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        if row["count"] == 0:
            connection.execute("DELETE FROM conversation_episodes WHERE id = ?", (episode_id,))
            return
        connection.execute(
            "UPDATE conversation_episodes SET message_count = ?, token_estimate = ?, started_at = ?, last_activity_at = ? WHERE id = ?",
            (row["count"], row["tokens"], row["started_at"], row["last_activity_at"], episode_id),
        )

    def _current_episode_row(self, connection: sqlite3.Connection) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT e.* FROM conversation_episodes e
            JOIN conversation_timelines t ON t.current_episode_id = e.id
            WHERE t.id = ? AND e.status = 'active'
            """,
            (PRIMARY_TIMELINE_ID,),
        ).fetchone()

    def _refresh_continuity_checkpoint(
        self, connection: sqlite3.Connection, episode_id: str, through_sequence: int,
    ) -> None:
        """Persist a compact, role-labelled checkpoint every second full turn.

        This is intentionally deterministic: it is a resilience layer between
        exact recent turns and the asynchronous semantic consolidation, never a
        second source of facts or an extra visible-turn model request.
        """
        count = int(connection.execute(
            """SELECT COUNT(*) FROM conversation_messages
               WHERE episode_id = ? AND status = 'completed' AND role IN ('user', 'assistant')""",
            (episode_id,),
        ).fetchone()[0])
        if count < 4 or count % 4:
            return
        rows = connection.execute(
            """SELECT id, role, content, corrected_content FROM conversation_messages
               WHERE episode_id = ? AND status = 'completed' AND role IN ('user', 'assistant')
               ORDER BY sequence_no DESC LIMIT 6""",
            (episode_id,),
        ).fetchall()
        rows = list(reversed(rows))
        source_ids = [str(row["id"]) for row in rows]
        summary = "\n".join(
            f"{row['role']}: {(row['corrected_content'] or row['content']).strip()}"
            for row in rows
        )[:1800]
        topic = " ".join(
            (row["corrected_content"] or row["content"]).strip()
            for row in rows[-2:] if row["role"] == "user"
        )[:300]
        now = self._now()
        connection.execute(
            "UPDATE episode_checkpoints SET superseded_at = ? WHERE episode_id = ? AND superseded_at IS NULL",
            (now, episode_id),
        )
        connection.execute(
            """INSERT OR REPLACE INTO episode_checkpoints
               (id, episode_id, through_sequence, topic_text, summary_text, decisions_json,
                open_questions_json, source_message_ids_json, created_at, superseded_at)
               VALUES (?, ?, ?, ?, ?, '[]', '[]', ?, ?, NULL)""",
            (uuid4().hex, episode_id, through_sequence, topic, summary,
             json.dumps(source_ids, ensure_ascii=False), now),
        )

    def _should_close_for_time(self, episode: sqlite3.Row, now: str, gap: float) -> bool:
        if gap >= self._episode_policy.hard_inactivity_seconds:
            return True
        return (
            self._day(episode["last_activity_at"]) != self._day(now)
            and gap >= self._episode_policy.soft_inactivity_seconds
        )

    def _publish_episode(self, event_type: str, level: str, message: str, episode_id: str, reason: str | None) -> None:
        if self._event_publisher is not None:
            self._event_publisher(event_type, level, message, {"timeline_id": PRIMARY_TIMELINE_ID, "episode_id": episode_id, "boundary_reason": reason})

    @staticmethod
    def _estimate_tokens(content: str) -> int:
        return max(1, (len(content) + 3) // 4)

    def _token_estimate_for_rows(self, connection: sqlite3.Connection, message_ids: list[str]) -> int:
        placeholders = ",".join("?" for _ in message_ids)
        row = connection.execute(f"SELECT COALESCE(SUM((length(content) + 3) / 4), 0) AS total FROM conversation_messages WHERE id IN ({placeholders})", message_ids).fetchone()
        return int(row["total"])

    @staticmethod
    def _day(value: str) -> str:
        return value[:10]

    @staticmethod
    def _seconds_between(previous: str, current: str) -> float:
        def parse(value: str) -> datetime:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=UTC) if "+" not in value[10:] else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return max(0.0, (parse(current) - parse(previous)).total_seconds())

    def _ensure_primary_timeline(self, connection: sqlite3.Connection) -> None:
        now = self._now()
        connection.execute(
            "INSERT OR IGNORE INTO companion_relationships (id, character_id, user_id, created_at, updated_at) VALUES (?, 'neuro', 'local_user', ?, ?)",
            (PRIMARY_RELATIONSHIP_ID, now, now),
        )
        connection.execute(
            "INSERT OR IGNORE INTO conversation_timelines (id, relationship_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (PRIMARY_TIMELINE_ID, PRIMARY_RELATIONSHIP_ID, now, now),
        )

    def _migrate_legacy_messages(self, connection: sqlite3.Connection) -> None:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'messages'").fetchone()
        if exists is None:
            return
        rows = connection.execute("SELECT id, session_id, role, content, created_at FROM messages ORDER BY id").fetchall()
        migrated_last_id: int | None = None
        migrated_last_created_at: str | None = None
        for row in rows:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO conversation_messages (
                    id, timeline_id, role, content, status, input_mode, created_at, completed_at,
                    legacy_source_id, metadata_json
                ) VALUES (?, ?, ?, ?, 'completed', 'text', ?, ?, ?, ?)
                """,
                (f"legacy-{row['id']}", PRIMARY_TIMELINE_ID, row["role"], row["content"], row["created_at"], row["created_at"], row["id"], json.dumps({"legacy_session_id": row["session_id"]})),
            )
            if cursor.rowcount:
                migrated_last_id = row["id"]
                migrated_last_created_at = row["created_at"]
        if migrated_last_id is not None and migrated_last_created_at is not None:
            self._touch_timeline(connection, f"legacy-{migrated_last_id}", migrated_last_created_at)

    def _backfill_continuity(self, connection: sqlite3.Connection) -> None:
        """Give historical rows deterministic order and conservative turn links.

        This runs only while sequence values are missing, so reopening a
        migrated database is a no-op.  Assistant rows are linked only to the
        immediately preceding user row; an orphan assistant receives its own
        legacy turn instead of inventing provenance.
        """
        missing = connection.execute(
            "SELECT 1 FROM conversation_messages WHERE sequence_no IS NULL LIMIT 1"
        ).fetchone()
        if missing is not None:
            rows = connection.execute(
                "SELECT id FROM conversation_messages WHERE timeline_id = ? ORDER BY created_at, id",
                (PRIMARY_TIMELINE_ID,),
            ).fetchall()
            # Temporarily clear values to avoid the unique index while a row
            # moves earlier in the deterministic legacy ordering.
            connection.execute("UPDATE conversation_messages SET sequence_no = NULL WHERE timeline_id = ?", (PRIMARY_TIMELINE_ID,))
            for number, row in enumerate(rows, 1):
                connection.execute("UPDATE conversation_messages SET sequence_no = ? WHERE id = ?", (number, row["id"]))

        rows = connection.execute(
            """SELECT id, role, turn_id, reply_to_message_id FROM conversation_messages
               WHERE timeline_id = ? ORDER BY sequence_no""",
            (PRIMARY_TIMELINE_ID,),
        ).fetchall()
        pending_user: sqlite3.Row | None = None
        for row in rows:
            if row["role"] == "user":
                turn_id = row["turn_id"] or f"legacy-turn-{row['id']}"
                if row["turn_id"] is None:
                    connection.execute("UPDATE conversation_messages SET turn_id = ? WHERE id = ?", (turn_id, row["id"]))
                pending_user = row
                continue
            if row["role"] == "assistant":
                if pending_user is not None:
                    turn_id = row["turn_id"] or pending_user["turn_id"] or f"legacy-turn-{pending_user['id']}"
                    reply_to = row["reply_to_message_id"] or pending_user["id"]
                    connection.execute(
                        "UPDATE conversation_messages SET turn_id = ?, reply_to_message_id = ? WHERE id = ?",
                        (turn_id, reply_to, row["id"]),
                    )
                elif row["turn_id"] is None:
                    connection.execute("UPDATE conversation_messages SET turn_id = ? WHERE id = ?", (f"legacy-turn-{row['id']}", row["id"]))
                pending_user = None
            else:
                pending_user = None

    @staticmethod
    def _next_sequence(connection: sqlite3.Connection) -> int:
        return int(connection.execute(
            "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM conversation_messages WHERE timeline_id = ?",
            (PRIMARY_TIMELINE_ID,),
        ).fetchone()[0])

    def _touch_timeline(self, connection: sqlite3.Connection, message_id: str, now: str) -> None:
        connection.execute("UPDATE conversation_timelines SET updated_at = ?, latest_message_id = ? WHERE id = ?", (now, message_id, PRIMARY_TIMELINE_ID))
        connection.execute("UPDATE companion_relationships SET updated_at = ?, last_interaction_at = ?, first_interaction_at = COALESCE(first_interaction_at, ?), total_interactions = total_interactions + 1 WHERE id = ?", (now, now, now, PRIMARY_RELATIONSHIP_ID))

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._db_path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def _immediate_connect(self) -> Iterator[sqlite3.Connection]:
        """A bounded writer transaction for causal turn lifecycle changes."""
        connection = sqlite3.connect(self._db_path, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> StoredTimelineMessage:
        return StoredTimelineMessage(
            id=row["id"], timeline_id=row["timeline_id"], session_id=row["session_id"], episode_id=row["episode_id"], role=row["role"], content=row["content"],
            corrected_content=row["corrected_content"], client_message_id=row["client_message_id"],
            utterance_id=row["utterance_id"], generation=row["generation"],
            sequence_no=int(row["sequence_no"] or 0), turn_id=row["turn_id"],
            reply_to_message_id=row["reply_to_message_id"],
            status=row["status"], input_mode=row["input_mode"], created_at=row["created_at"],
            language=row["language"],
            completed_at=row["completed_at"], cancelled_at=row["cancelled_at"], metadata=json.loads(row["metadata_json"]),
        )


class TimelineHistoryAdapter:
    """V0.4 history contract backed by the single primary timeline."""

    def __init__(self, store: TimelineStore) -> None:
        self._store = store

    def init_db(self) -> None:
        self._store.init_db()

    def save_message(
        self, session_id: str, role: str, content: str, input_mode: str = "text",
        *, turn_id: str | None = None, reply_to_message_id: str | None = None,
    ) -> StoredTimelineMessage:
        message, _ = self._store.append_message(
            role=role, content=content, input_mode=input_mode,
            turn_id=turn_id, reply_to_message_id=reply_to_message_id,
            metadata={"legacy_session_id": session_id}, session_id=session_id,
        )
        return message

    def apply_voice_interpretation(
        self, message_id: str, corrected_content: str, replacement_count: int,
    ) -> StoredTimelineMessage:
        return self._store.apply_voice_interpretation(message_id, corrected_content, replacement_count)

    def get_recent_messages(self, session_id: str, limit: int) -> list[ChatMessage]:
        return self._store.get_recent_messages(session_id, limit)

    def check_health(self) -> bool:
        return self._store.check_health()
