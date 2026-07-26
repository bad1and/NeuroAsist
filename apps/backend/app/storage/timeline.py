"""Versioned SQLite storage for the single V0.5 companion timeline."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from apps.backend.app.llm.base import ChatMessage


PRIMARY_RELATIONSHIP_ID = "primary"
PRIMARY_TIMELINE_ID = "primary-timeline"


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
    episode_id: str | None
    role: str
    content: str
    corrected_content: str | None
    client_message_id: str | None
    status: str
    input_mode: str
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
            "episode_id": self.episode_id,
            "role": self.role,
            "content": self.effective_content,
            "original_content": self.content,
            "corrected_content": self.corrected_content,
            "client_message_id": self.client_message_id,
            "status": self.status,
            "input_mode": self.input_mode,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "cancelled_at": self.cancelled_at,
            "metadata": self.metadata,
        }


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
            self._ensure_primary_timeline(connection)
            self._migrate_legacy_messages(connection)
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
        metadata: dict[str, object] | None = None,
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
            if client_message_id:
                existing = connection.execute(
                    "SELECT * FROM conversation_messages WHERE timeline_id = ? AND client_message_id = ?",
                    (PRIMARY_TIMELINE_ID, client_message_id),
                ).fetchone()
                if existing is not None:
                    return self._row_to_message(existing), False
            now = created_at or self._now()
            episode_id = self._ensure_active_episode(connection, now, content) if self._episode_policy.enabled else None
            message_id = uuid4().hex
            completed_at = now if status == "completed" else None
            try:
                connection.execute(
                    """
                    INSERT INTO conversation_messages (
                        id, timeline_id, episode_id, role, content, client_message_id, status, input_mode,
                        created_at, completed_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (message_id, PRIMARY_TIMELINE_ID, episode_id, role, content, client_message_id, status,
                     input_mode, now, completed_at, json.dumps(metadata or {}, ensure_ascii=False)),
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
            self._index_timeline_message(connection, message_id, content)
            row = connection.execute("SELECT * FROM conversation_messages WHERE id = ?", (message_id,)).fetchone()
            return self._row_to_message(row), True

    def get_recent_messages(self, _session_id: str, limit: int) -> list[ChatMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, corrected_content FROM conversation_messages
                WHERE timeline_id = ? AND status = 'completed' AND role IN ('user', 'assistant')
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (PRIMARY_TIMELINE_ID, limit),
            ).fetchall()
        return [ChatMessage(role=row["role"], content=row["corrected_content"] or row["content"]) for row in reversed(rows)]

    def list_messages(self, limit: int, offset: int = 0) -> tuple[list[StoredTimelineMessage], int | None]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_messages WHERE timeline_id = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
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
                       WHERE timeline_message_fts MATCH ? AND m.timeline_id = ? ORDER BY bm25(timeline_message_fts), m.created_at DESC LIMIT ?""",
                    (fts_query, PRIMARY_TIMELINE_ID, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM conversation_messages
                    WHERE timeline_id = ? AND (content LIKE ? ESCAPE '\\' OR corrected_content LIKE ? ESCAPE '\\')
                    ORDER BY created_at DESC, id DESC LIMIT ?""",
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
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM background_jobs WHERE type = 'episode_summary' AND status = 'pending' AND available_at <= ? ORDER BY available_at, created_at LIMIT 1", (self._now(),)).fetchone()
            if row is None:
                return None
            connection.execute("UPDATE background_jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?", (self._now(), row["id"]))
            return dict(row)

    def enqueue_memory_index_job(self, memory_id: str) -> None:
        """Durably coalesce Chroma updates; SQLite remains the source of truth."""
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE background_jobs SET status = 'completed' WHERE type = 'memory_index' AND status = 'pending' AND json_extract(payload_json, '$.memory_id') = ?",
                (memory_id,),
            )
            connection.execute(
                "INSERT INTO background_jobs (id, type, status, payload_json, available_at, created_at, updated_at) VALUES (?, 'memory_index', 'pending', ?, ?, ?, ?)",
                (uuid4().hex, json.dumps({"memory_id": memory_id}), now, now, now),
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
                "UPDATE background_jobs SET status = 'completed', updated_at = ? WHERE type = 'memory_extract' AND status = 'pending' AND json_extract(payload_json, '$.message_id') = ?",
                (now, message_id),
            )
            connection.execute(
                "INSERT INTO background_jobs (id, type, status, payload_json, available_at, created_at, updated_at) VALUES (?, 'memory_extract', 'pending', ?, ?, ?, ?)",
                (uuid4().hex, json.dumps({"message_id": message_id}), now, now, now),
            )

    def claim_memory_extraction_job(self) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM background_jobs WHERE type = 'memory_extract' AND status = 'pending' AND available_at <= ? ORDER BY available_at, created_at LIMIT 1", (self._now(),)).fetchone()
            if row is None:
                return None
            connection.execute("UPDATE background_jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?", (self._now(), row["id"]))
            return dict(row)

    def claim_memory_index_job(self) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM background_jobs WHERE type = 'memory_index' AND status = 'pending' AND available_at <= ? ORDER BY available_at, created_at LIMIT 1", (self._now(),)).fetchone()
            if row is None:
                return None
            connection.execute("UPDATE background_jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?", (self._now(), row["id"]))
            return dict(row)

    def recover_memory_index_jobs(self) -> None:
        """A process crash may leave a claimed job running; make it retry on startup."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE background_jobs SET status = 'pending', available_at = ?, updated_at = ? WHERE type IN ('memory_index', 'memory_extract') AND status = 'running'",
                (self._now(), self._now()),
            )

    def complete_summary_job(self, job_id: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE background_jobs SET status = 'completed', updated_at = ? WHERE id = ?", (self._now(), job_id))

    def fail_summary_job(self, job_id: str, error: str) -> None:
        with self._connect() as connection:
            job = connection.execute("SELECT attempts FROM background_jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                return
            now = datetime.now(UTC)
            if job["attempts"] < 3:
                delay_seconds = 2 ** job["attempts"]
                connection.execute(
                    "UPDATE background_jobs SET status = 'pending', available_at = ?, error_text = ?, updated_at = ? WHERE id = ?",
                    ((now + timedelta(seconds=delay_seconds)).isoformat(timespec="milliseconds"), error[:500], now.isoformat(timespec="milliseconds"), job_id),
                )
            else:
                connection.execute("UPDATE background_jobs SET status = 'failed', error_text = ?, updated_at = ? WHERE id = ?", (error[:500], now.isoformat(timespec="milliseconds"), job_id))

    def summarize_episode(self, episode_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            episode = connection.execute("SELECT * FROM conversation_episodes WHERE id = ?", (episode_id,)).fetchone()
            if episode is None or episode["message_count"] == 0:
                return None
            rows = connection.execute("SELECT id, role, content, corrected_content FROM conversation_messages WHERE episode_id = ? ORDER BY created_at, id", (episode_id,)).fetchall()
            user_texts = [(row["corrected_content"] or row["content"]).strip() for row in rows if row["role"] == "user"]
            decisions = [text for text in user_texts if any(marker in text.lower() for marker in ("решил", "решили", "нужно", "не делать", "будем"))][:5]
            open_loops = [text for text in user_texts if "?" in text][-3:]
            topics = self._keywords(" ".join(user_texts))[:5]
            summary_text = " ".join(user_texts[:1] + user_texts[-1:])[:900] or "Conversation episode"
            version = connection.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM episode_summaries WHERE episode_id = ?", (episode_id,)).fetchone()[0]
            now = self._now()
            connection.execute("UPDATE episode_summaries SET superseded_at = ? WHERE episode_id = ? AND superseded_at IS NULL", (now, episode_id))
            summary_id = uuid4().hex
            connection.execute("""INSERT INTO episode_summaries (id, episode_id, version, summary_text, topics_json, decisions_json, open_loops_json, source_message_ids_json, prompt_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'deterministic-v1', ?)""", (summary_id, episode_id, version, summary_text, json.dumps(topics, ensure_ascii=False), json.dumps(decisions, ensure_ascii=False), json.dumps(open_loops, ensure_ascii=False), json.dumps([row["id"] for row in rows]), now))
            connection.execute("INSERT INTO episode_summary_fts (summary_id, text) VALUES (?, ?)", (summary_id, summary_text))
            connection.execute("UPDATE conversation_episodes SET summary_status = 'summarized', summary_version = ? WHERE id = ?", (version, episode_id))
            return {"id": summary_id, "episode_id": episode_id, "summary_text": summary_text, "topics": topics, "decisions": decisions, "open_loops": open_loops}

    def get_message(self, message_id: str) -> StoredTimelineMessage | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM conversation_messages WHERE id = ? AND timeline_id = ?", (message_id, PRIMARY_TIMELINE_ID)).fetchone()
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
                     AND (created_at < ? OR (created_at = ? AND id <= ?))
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (PRIMARY_TIMELINE_ID, target["created_at"], target["created_at"], target["id"], max(1, limit)),
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
                    created_at, updated_at, last_accessed_at, access_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, 0, '{}')""",
                (memory_id, PRIMARY_RELATIONSHIP_ID, values["scope"], values["kind"], values["subject"], values["predicate"],
                 values["value_text"], canonical, values.get("importance", 0.5), values.get("confidence", 0.5),
                 values.get("sensitivity", "normal"), values.get("status", "candidate"), int(bool(values.get("user_locked", False))),
                 values.get("valid_from"), values.get("valid_to"), values.get("expires_at"), source_episode_id,
                 json.dumps(source_ids, ensure_ascii=False), values.get("extractor_version", "memory-v1"), now, now),
            )
            self._index_memory(connection, memory_id, canonical)
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
                "memory_usage",
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
                "UPDATE conversation_timelines SET current_episode_id = NULL, latest_message_id = NULL, updated_at = ? WHERE id = ?",
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
            return len(rows)

    def semantic_index_items(self, namespace: str) -> list[tuple[str, str]]:
        with self._connect() as connection:
            if namespace == "memory":
                rows = connection.execute("SELECT id, canonical_text FROM memory_items WHERE status = 'active'").fetchall()
            elif namespace == "episode_summary":
                rows = connection.execute("SELECT id, summary_text FROM episode_summaries WHERE superseded_at IS NULL").fetchall()
            else:
                raise ValueError(f"Unsupported semantic namespace: {namespace}")
        return [(row["id"], row[1]) for row in rows]

    def context_material(self, user_text: str, recent_turns: int) -> dict[str, object]:
        with self._connect() as connection:
            active = self._current_episode_row(connection)
            active_id = active["id"] if active else ""
            recent = connection.execute("SELECT role, content, corrected_content FROM conversation_messages WHERE timeline_id = ? AND status = 'completed' AND role IN ('user','assistant') ORDER BY created_at DESC, id DESC LIMIT ?", (PRIMARY_TIMELINE_ID, recent_turns * 2)).fetchall()
            terms = self._keywords(user_text)
            if terms:
                clauses = " OR ".join("s.summary_text LIKE ?" for _ in terms)
                summaries = connection.execute(f"SELECT s.* FROM episode_summaries s WHERE s.superseded_at IS NULL AND s.episode_id != ? AND ({clauses}) ORDER BY s.created_at DESC LIMIT 2", (active_id, *(f"%{term}%" for term in terms))).fetchall()
            else:
                summaries = []
            if not summaries:
                summaries = connection.execute("SELECT s.* FROM episode_summaries s WHERE s.superseded_at IS NULL AND s.episode_id != ? ORDER BY s.created_at DESC LIMIT 2", (active_id,)).fetchall()
            rolling_summary = None
            if active_id:
                active_rows = connection.execute("SELECT role, content, corrected_content FROM conversation_messages WHERE episode_id = ? AND status = 'completed' AND role IN ('user','assistant') ORDER BY created_at, id", (active_id,)).fetchall()
                older_rows = active_rows[: max(0, len(active_rows) - recent_turns * 2)]
                if older_rows:
                    older_user_texts = [(row["corrected_content"] or row["content"]).strip() for row in older_rows if row["role"] == "user"]
                    rolling_summary = " ".join(older_user_texts[:1] + older_user_texts[-1:])[:700] or None
        return {"active_episode_id": active_id or None, "recent": list(reversed(recent)), "summaries": [dict(row) for row in summaries], "rolling_summary": rolling_summary}

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

    def _touch_timeline(self, connection: sqlite3.Connection, message_id: str, now: str) -> None:
        connection.execute("UPDATE conversation_timelines SET updated_at = ?, latest_message_id = ? WHERE id = ?", (now, message_id, PRIMARY_TIMELINE_ID))
        connection.execute("UPDATE companion_relationships SET updated_at = ?, last_interaction_at = ?, first_interaction_at = COALESCE(first_interaction_at, ?), total_interactions = total_interactions + 1 WHERE id = ?", (now, now, now, PRIMARY_RELATIONSHIP_ID))

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> StoredTimelineMessage:
        return StoredTimelineMessage(
            id=row["id"], timeline_id=row["timeline_id"], episode_id=row["episode_id"], role=row["role"], content=row["content"],
            corrected_content=row["corrected_content"], client_message_id=row["client_message_id"],
            status=row["status"], input_mode=row["input_mode"], created_at=row["created_at"],
            completed_at=row["completed_at"], cancelled_at=row["cancelled_at"], metadata=json.loads(row["metadata_json"]),
        )


class TimelineHistoryAdapter:
    """V0.4 history contract backed by the single primary timeline."""

    def __init__(self, store: TimelineStore) -> None:
        self._store = store

    def init_db(self) -> None:
        self._store.init_db()

    def save_message(self, session_id: str, role: str, content: str, input_mode: str = "text") -> StoredTimelineMessage:
        message, _ = self._store.append_message(role=role, content=content, input_mode=input_mode, metadata={"legacy_session_id": session_id})
        return message

    def apply_voice_interpretation(
        self, message_id: str, corrected_content: str, replacement_count: int,
    ) -> StoredTimelineMessage:
        return self._store.apply_voice_interpretation(message_id, corrected_content, replacement_count)

    def get_recent_messages(self, session_id: str, limit: int) -> list[ChatMessage]:
        return self._store.get_recent_messages(session_id, limit)

    def check_health(self) -> bool:
        return self._store.check_health()
