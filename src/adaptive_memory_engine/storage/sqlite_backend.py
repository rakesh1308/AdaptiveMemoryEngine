"""SQLite backend — durable storage for memories, embeddings, and access log.

Schema: tables `memories`, `embeddings`, `access_log`, virtual table
`memories_fts` (FTS5, external-content). PRAGMAs are tuned for local-disk
durability: `journal_mode=DELETE`, `synchronous=NORMAL`, `locking_mode=NORMAL`.
Embedding BLOBs are little-endian float32.
"""
from __future__ import annotations

import json
import sqlite3
import struct
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..events import now_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id            TEXT PRIMARY KEY,
  content       TEXT NOT NULL,
  tags          TEXT DEFAULT '[]',
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  importance    INTEGER DEFAULT 50,
  strength      REAL DEFAULT 1.0,
  access_count  INTEGER DEFAULT 0,
  source        TEXT DEFAULT 'user',
  version       INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS embeddings (
  memory_id   TEXT PRIMARY KEY,
  embedding   BLOB,
  updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS access_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id    TEXT,
  accessed_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  context      TEXT,
  FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
CREATE INDEX IF NOT EXISTS idx_memories_updated    ON memories(updated_at);
CREATE INDEX IF NOT EXISTS idx_access_log_memory   ON access_log(memory_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  id, content, tags,
  content='memories', content_rowid='rowid'
);
"""

# v2.1.0: version history (every edit snapshots prior state)
# NOTE: no ON DELETE CASCADE — versions outlive the memory row so that
# restoring after a delete still works. Orphan versions are pruned
# explicitly by delete_with_history().
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS memory_versions (
  version_id  TEXT PRIMARY KEY,
  memory_id   TEXT NOT NULL,
  content     TEXT NOT NULL,
  tags        TEXT DEFAULT '[]',
  importance  INTEGER DEFAULT 50,
  version_num INTEGER DEFAULT 1,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  source      TEXT DEFAULT 'mcp'
);
CREATE INDEX IF NOT EXISTS idx_versions_memory ON memory_versions(memory_id, created_at DESC);
"""

# v2.2.0: memory suggestions (dedup / contradiction / stale proposals)
# Suggestions are independent of their target memories — they survive
# even if a target is deleted, so we don't FK-cascade.
_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS memory_suggestions (
  suggestion_id TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,        -- 'merge' | 'contradiction' | 'stale' | 'duplicate'
  status        TEXT NOT NULL,        -- 'open' | 'applied' | 'dismissed'
  target_ids    TEXT NOT NULL,        -- JSON array of memory ids involved
  summary       TEXT NOT NULL,        -- human-readable description
  payload       TEXT DEFAULT '{}',    -- JSON, kind-specific data (e.g. merged_content)
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  resolved_at   DATETIME
);
CREATE INDEX IF NOT EXISTS idx_suggestions_status ON memory_suggestions(status, created_at DESC);
"""


class SQLiteBackend:
    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "memories.db"
        self.data_dir = Path(data_dir)
        self._conn: sqlite3.Connection | None = None

    # ---- lifecycle ----

    def initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Match Node PRAGMAs exactly (GCS FUSE compatibility)
        self._conn.execute("PRAGMA journal_mode = DELETE")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA locking_mode = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        # Idempotent additive migrations
        self._conn.executescript(_SCHEMA_V2)
        self._conn.executescript(_SCHEMA_V3)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SQLiteBackend not initialized")
        return self._conn

    # ---- memory CRUD ----

    def insert(self, memory: dict[str, Any]) -> None:
        tags_json = json.dumps(memory.get("tags", []), ensure_ascii=False)
        now = now_iso()
        # Use UPDATE-then-INSERT instead of INSERT OR REPLACE so that we
        # don't fire ON DELETE CASCADE on dependent tables (memory_versions,
        # memory_suggestions, embeddings, access_log).
        existing = self.conn.execute(
            "SELECT 1 FROM memories WHERE id = ?", (memory["id"],)
        ).fetchone()
        if existing:
            self.conn.execute(
                """
                UPDATE memories SET
                  content = ?, tags = ?, updated_at = ?,
                  importance = ?, strength = ?, access_count = ?,
                  source = ?, version = ?
                WHERE id = ?
                """,
                (
                    memory["content"],
                    tags_json,
                    memory.get("updatedAt") or now,
                    int(memory.get("importance", 50)),
                    float(memory.get("strength", 1.0)),
                    int(memory.get("accessCount", 0)),
                    memory.get("source", "user"),
                    int(memory.get("version", 1)),
                    memory["id"],
                ),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO memories
                  (id, content, tags, created_at, updated_at, importance, strength,
                   access_count, source, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory["id"],
                    memory["content"],
                    tags_json,
                    memory.get("createdAt") or now,
                    memory.get("updatedAt") or now,
                    int(memory.get("importance", 50)),
                    float(memory.get("strength", 1.0)),
                    int(memory.get("accessCount", 0)),
                    memory.get("source", "user"),
                    int(memory.get("version", 1)),
                ),
            )
        # FTS upsert — match Node's `(memory.tags || []).join(' ')` shape
        tags_space = " ".join(memory.get("tags") or [])
        self.conn.execute(
            "INSERT INTO memories_fts(memories_fts, id, content, tags) VALUES('delete', ?, ?, ?)",
            (memory["id"], memory["content"], tags_space),
        )
        self.conn.execute(
            "INSERT INTO memories_fts(rowid, id, content, tags) "
            "SELECT rowid, id, content, tags FROM memories WHERE id = ?",
            (memory["id"],),
        )

    def get(self, memory_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def get_all(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM memories ORDER BY updated_at DESC"
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def delete(self, memory_id: str) -> None:
        # FK cascades remove embeddings + access_log
        self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.conn.execute(
            "INSERT INTO memories_fts(memories_fts, id, content, tags) VALUES('delete', ?, '', '')",
            (memory_id,),
        )
        # Explicitly prune version history (no FK cascade — versions outlive
        # the memory row by design, until the memory is explicitly deleted).
        self.conn.execute(
            "DELETE FROM memory_versions WHERE memory_id = ?", (memory_id,)
        )

    def update(self, memory_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get(memory_id)
        if not existing:
            return None
        allowed = {"content", "tags", "importance", "strength", "accessCount"}
        sets: list[str] = []
        params: list[Any] = []
        for k, v in updates.items():
            if k not in allowed:
                continue
            if k == "tags":
                sets.append("tags = ?")
                params.append(json.dumps(v, ensure_ascii=False))
            else:
                col = {"accessCount": "access_count"}.get(k, k)
                sets.append(f"{col} = ?")
                params.append(v)
        if not sets:
            return existing
        sets.append("updated_at = ?")
        params.append(now_iso())
        params.append(memory_id)
        self.conn.execute(
            f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", params
        )
        # Refresh FTS row if content or tags changed
        if "content" in updates or "tags" in updates:
            refreshed = self.get(memory_id)
            if refreshed:
                tags_space = " ".join(refreshed.get("tags") or [])
                self.conn.execute(
                    "INSERT INTO memories_fts(memories_fts, id, content, tags) VALUES('delete', ?, '', '')",
                    (memory_id,),
                )
                self.conn.execute(
                    "INSERT INTO memories_fts(rowid, id, content, tags) "
                    "SELECT rowid, id, content, tags FROM memories WHERE id = ?",
                    (memory_id,),
                )
                # ensure tags index uses space-separated
                self.conn.execute(
                    "UPDATE memories_fts SET tags = ? WHERE id = ?",
                    (tags_space, memory_id),
                )
        return self.get(memory_id)

    # ---- search ----

    def search_keyword(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """FTS5 with LIKE fallback (matches Node)."""
        try:
            # Sanitize FTS query — strip non-word chars except spaces/quotes
            q = "".join(c for c in query if c.isalnum() or c in " '\"").strip()
            if q:
                rows = self.conn.execute(
                    "SELECT m.* FROM memories_fts f "
                    "JOIN memories m ON m.rowid = f.rowid "
                    "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                    (q, limit),
                ).fetchall()
                return [self._row_to_memory(r) for r in rows]
        except sqlite3.OperationalError:
            pass
        # Fallback
        like = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE content LIKE ? OR tags LIKE ? OR id LIKE ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (like, like, like, limit),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def get_by_tag(self, tag: str) -> list[dict[str, Any]]:
        # Match Node: tags stored as JSON, search for "tag" with surrounding quotes.
        like = f'%"{tag}"%'
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE tags LIKE ? ORDER BY updated_at DESC",
            (like,),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    # ---- embeddings ----

    def save_embedding(self, memory_id: str, embedding: list[float]) -> None:
        # Last-chunk-wins (matches Node: INSERT OR REPLACE on memory_id only)
        buf = struct.pack(f"<{len(embedding)}f", *embedding)
        self.conn.execute(
            "INSERT OR REPLACE INTO embeddings (memory_id, embedding, updated_at) "
            "VALUES (?, ?, ?)",
            (memory_id, buf, now_iso()),
        )

    def get_embedding(self, memory_id: str) -> list[float] | None:
        row = self.conn.execute(
            "SELECT embedding FROM embeddings WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if not row or row["embedding"] is None:
            return None
        n = len(row["embedding"]) // 4
        return list(struct.unpack(f"<{n}f", row["embedding"]))

    def get_all_embeddings(self) -> "OrderedDict[str, list[float]]":
        rows = self.conn.execute(
            "SELECT memory_id, embedding FROM embeddings"
        ).fetchall()
        out: OrderedDict[str, list[float]] = OrderedDict()
        for r in rows:
            if r["embedding"] is None:
                continue
            n = len(r["embedding"]) // 4
            out[r["memory_id"]] = list(struct.unpack(f"<{n}f", r["embedding"]))
        return out

    # ---- access log ----

    def record_access(self, memory_id: str, context: dict | None = None) -> None:
        ctx_json = json.dumps(context or {}, ensure_ascii=False)
        self.conn.execute(
            "INSERT INTO access_log (memory_id, context) VALUES (?, ?)",
            (memory_id, ctx_json),
        )
        self.conn.execute(
            "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
            (memory_id,),
        )

    # ---- stats ----

    def get_stats(self) -> dict[str, int]:
        total = self.conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]
        with_emb = self.conn.execute(
            "SELECT COUNT(*) AS n FROM embeddings"
        ).fetchone()["n"]
        return {"total": total, "withEmbeddings": with_emb}

    # ---- helpers ----

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except json.JSONDecodeError:
            d["tags"] = []
        d["createdAt"] = d.pop("created_at", None)
        d["updatedAt"] = d.pop("updated_at", None)
        d["accessCount"] = d.pop("access_count", 0)
        return d

    # ---- version history (v2.1) ----

    def snapshot_version(self, memory: dict[str, Any]) -> str:
        """Append a version-history row capturing the memory's *prior* state.
        Called by MemoryEngine.store_memory() before overwriting an existing memory.
        Returns the version_id."""
        import uuid
        version_id = str(uuid.uuid4())
        tags_json = json.dumps(memory.get("tags", []), ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO memory_versions
              (version_id, memory_id, content, tags, importance, version_num, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                memory["id"],
                memory.get("content", ""),
                tags_json,
                int(memory.get("importance", 50)),
                int(memory.get("version", 1)),
                memory.get("source", "user"),
            ),
        )
        return version_id

    def get_versions(self, memory_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM memory_versions WHERE memory_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (memory_id, int(limit)),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["tags"] = json.loads(d.get("tags") or "[]")
            except json.JSONDecodeError:
                d["tags"] = []
            d["createdAt"] = d.pop("created_at", None)
            out.append(d)
        return out

    def get_version(self, version_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM memory_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except json.JSONDecodeError:
            d["tags"] = []
        d["createdAt"] = d.pop("created_at", None)
        return d

    # ---- suggestions (v2.2) ----

    def create_suggestion(
        self,
        kind: str,
        target_ids: list[str],
        summary: str,
        payload: dict | None = None,
    ) -> str:
        import uuid
        sid = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO memory_suggestions
              (suggestion_id, kind, status, target_ids, summary, payload)
            VALUES (?, ?, 'open', ?, ?, ?)
            """,
            (
                sid,
                kind,
                json.dumps(target_ids, ensure_ascii=False),
                summary,
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        return sid

    def list_suggestions(self, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM memory_suggestions WHERE status = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (status, int(limit)),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["target_ids"] = json.loads(d.get("target_ids") or "[]")
                d["payload"] = json.loads(d.get("payload") or "{}")
            except json.JSONDecodeError:
                d["target_ids"] = []
                d["payload"] = {}
            d["createdAt"] = d.pop("created_at", None)
            d["resolvedAt"] = d.pop("resolved_at", None)
            out.append(d)
        return out

    def get_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM memory_suggestions WHERE suggestion_id = ?",
            (suggestion_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["target_ids"] = json.loads(d.get("target_ids") or "[]")
            d["payload"] = json.loads(d.get("payload") or "{}")
        except json.JSONDecodeError:
            d["target_ids"] = []
            d["payload"] = {}
        d["createdAt"] = d.pop("created_at", None)
        d["resolvedAt"] = d.pop("resolved_at", None)
        return d

    def resolve_suggestion(self, suggestion_id: str, status: str) -> bool:
        if status not in ("applied", "dismissed"):
            raise ValueError("status must be 'applied' or 'dismissed'")
        cur = self.conn.execute(
            "UPDATE memory_suggestions SET status = ?, resolved_at = ? "
            "WHERE suggestion_id = ? AND status = 'open'",
            (status, now_iso(), suggestion_id),
        )
        return cur.rowcount > 0