import sqlite3
from contextlib import closing
from pathlib import Path

from apps.backend.app.memory.service import MemoryService
from apps.backend.app.runtime.settings import RuntimeSettings
from apps.backend.app.storage.timeline import PRIMARY_TIMELINE_ID, TimelineStore


def _populated_store(database: Path) -> tuple[TimelineStore, str, str]:
    store = TimelineStore(database)
    store.init_db()
    message, _ = store.append_message(role="user", content="Меня зовут Роман", input_mode="text")
    MemoryService(store, RuntimeSettings(memory_mode="automatic")).extract_from_message(message)
    assert message.episode_id is not None
    return store, message.id, message.episode_id


def _table_count(database: Path, table: str) -> int:
    with closing(sqlite3.connect(database)) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_reset_companion_data_keeps_v5_database_compatible(tmp_path: Path) -> None:
    database = tmp_path / "v5.sqlite3"
    store, _, _ = _populated_store(database)

    result = store.reset_companion_data()

    assert result == {"messages": 1, "memories": 1, "episodes": 1}
    assert store.list_messages(10)[0] == []
    assert store.list_memories(limit=10) == []
    with closing(sqlite3.connect(database)) as connection:
        pointers = connection.execute(
            "SELECT current_episode_id, latest_message_id FROM conversation_timelines WHERE id = ?",
            (PRIMARY_TIMELINE_ID,),
        ).fetchone()
    assert pointers == (None, None)


def test_reset_companion_data_clears_optional_v9_children_before_parents(tmp_path: Path) -> None:
    database = tmp_path / "v9.sqlite3"
    store, message_id, episode_id = _populated_store(database)

    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE memory_scopes (id TEXT PRIMARY KEY);
            CREATE TABLE memory_operations (
                id TEXT PRIMARY KEY,
                source_message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
                episode_id TEXT NOT NULL REFERENCES conversation_episodes(id) ON DELETE CASCADE,
                job_id TEXT REFERENCES background_jobs(id)
            );
            CREATE TABLE memory_retrieval_runs (id TEXT PRIMARY KEY);
            CREATE TABLE memory_usage (
                id TEXT PRIMARY KEY,
                retrieval_run_id TEXT NOT NULL REFERENCES memory_retrieval_runs(id) ON DELETE CASCADE
            );
            CREATE TABLE graph_nodes (
                id TEXT PRIMARY KEY,
                memory_scope_id TEXT NOT NULL REFERENCES memory_scopes(id)
            );
            CREATE TABLE graph_edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES graph_nodes(id),
                target_id TEXT NOT NULL REFERENCES graph_nodes(id)
            );
            CREATE TABLE graph_edge_evidence (
                id TEXT PRIMARY KEY,
                edge_id TEXT NOT NULL REFERENCES graph_edges(id) ON DELETE CASCADE,
                episode_id TEXT NOT NULL REFERENCES conversation_episodes(id) ON DELETE CASCADE,
                source_message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE
            );
            CREATE TABLE memory_contradictions (id TEXT PRIMARY KEY);
            CREATE TABLE graph_audit (id TEXT PRIMARY KEY);
            CREATE VIRTUAL TABLE graph_nodes_fts USING fts5(node_id UNINDEXED, text);
            """
        )
        now = "2026-07-18T00:00:00+00:00"
        connection.execute(
            "INSERT INTO background_jobs (id, type, status, payload_json, available_at, created_at, updated_at) VALUES ('job', 'memory_extract', 'completed', '{}', ?, ?, ?)",
            (now, now, now),
        )
        connection.execute("INSERT INTO memory_operations VALUES ('operation', ?, ?, 'job')", (message_id, episode_id))
        connection.execute("INSERT INTO memory_retrieval_runs VALUES ('run')")
        connection.execute("INSERT INTO memory_usage VALUES ('usage', 'run')")
        connection.execute("INSERT INTO memory_scopes VALUES ('scope')")
        connection.execute("INSERT INTO graph_nodes VALUES ('source', 'scope')")
        connection.execute("INSERT INTO graph_nodes VALUES ('target', 'scope')")
        connection.execute("INSERT INTO graph_edges VALUES ('edge', 'source', 'target')")
        connection.execute("INSERT INTO graph_edge_evidence VALUES ('evidence', 'edge', ?, ?)", (episode_id, message_id))
        connection.execute("INSERT INTO memory_contradictions VALUES ('contradiction')")
        connection.execute("INSERT INTO graph_audit VALUES ('audit')")
        connection.execute("INSERT INTO graph_nodes_fts VALUES ('source', 'Роман')")

    result = store.reset_companion_data()

    assert result == {"messages": 1, "memories": 1, "episodes": 1}
    for table in (
        "memory_operations",
        "memory_retrieval_runs",
        "memory_usage",
        "graph_nodes",
        "graph_edges",
        "graph_edge_evidence",
        "memory_contradictions",
        "graph_audit",
        "graph_nodes_fts",
        "background_jobs",
        "conversation_messages",
        "conversation_episodes",
        "memory_items",
    ):
        assert _table_count(database, table) == 0
    # The scope is schema scaffolding. Keeping it allows a newer core to resume
    # without rerunning an already-recorded migration.
    assert _table_count(database, "memory_scopes") == 1
