"""SQLite memory store: one file, keyword (FTS5) + semantic (local vectors) search."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .embedder import Embedder, data_dir

log = logging.getLogger(__name__)

MAX_CONTENT = 20_000  # characters; memories are short facts, not documents
MAX_KEY = 200

# Question words and glue words match almost every memory; they must not drive keyword search.
STOPWORDS = frozenset(
    "a an the and or but if of to in on at by for with from as is are was were be been being do does "
    "did how what which who whom whose when where why we our us you your i me my it its this that "
    "these those can could should would will shall may might not no so than then there their they "
    "them he she his her has have had about into over under up down out".split()
)
KEYWORD_BONUS = 0.005  # tie-break only: larger bonuses lowered paraphrase accuracy in study/eval_embeddings.py

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  key        TEXT PRIMARY KEY,
  content    TEXT NOT NULL,
  tags       TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vectors (
  key   TEXT PRIMARY KEY REFERENCES memories(key) ON DELETE CASCADE,
  model TEXT NOT NULL,
  vec   BLOB NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  key, content, tags, content='memories', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, key, content, tags) VALUES (new.rowid, new.key, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, key, content, tags) VALUES ('delete', old.rowid, old.key, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, key, content, tags) VALUES ('delete', old.rowid, old.key, old.content, old.tags);
  INSERT INTO memories_fts(rowid, key, content, tags) VALUES (new.rowid, new.key, new.content, new.tags);
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(r: sqlite3.Row) -> dict:
    return {
        "key": r["key"],
        "content": r["content"],
        "tags": json.loads(r["tags"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


class MemoryStore:
    def __init__(self, path: str | Path | None = None, embedder: Embedder | None = None) -> None:
        self.path = Path(path or os.environ.get("ADAPTIVE_MEMORY_DB") or data_dir() / "memory.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or Embedder()
        self._lock = threading.RLock()
        self._cache: tuple | None = None
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=30, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        """Switch to WAL and create tables. Retries because the very first open by two
        processes at once can fail with 'database is locked' before the busy timeout applies."""
        deadline = time.monotonic() + 15
        while True:
            try:
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.executescript(SCHEMA)
                return
            except sqlite3.OperationalError as e:
                if "locked" not in str(e) or time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    @contextmanager
    def _write(self):
        """Serialize writers across threads and processes.

        BEGIN IMMEDIATE takes the write lock up front, so SQLite waits (busy timeout)
        instead of failing with 'database is locked' on a read-to-write upgrade.
        """
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
            self._cache = None

    # ---- writes ----

    def store(self, key: str, content: str, tags: list[str] | None = None) -> dict:
        key, content = key.strip(), content.strip()
        if not key or not content:
            raise ValueError("key and content must not be empty")
        if len(key) > MAX_KEY or len(content) > MAX_CONTENT:
            raise ValueError(f"key max {MAX_KEY} chars, content max {MAX_CONTENT} chars")
        tag_list = sorted({t.strip().lower() for t in (tags or []) if t.strip()})
        now = _now()
        with self._write():
            existing = self._db.execute("SELECT created_at FROM memories WHERE key=?", (key,))
            row = existing.fetchone()
            if row:
                self._db.execute(
                    "UPDATE memories SET content=?, tags=?, updated_at=? WHERE key=?",
                    (content, json.dumps(tag_list), now, key),
                )
            else:
                self._db.execute(
                    "INSERT INTO memories(key, content, tags, created_at, updated_at) "
                    "VALUES (?,?,?,?,?)",
                    (key, content, json.dumps(tag_list), now, now),
                )
            self._db.execute("DELETE FROM vectors WHERE key=?", (key,))
        self._embed_missing([key])  # best effort; search retries anything still missing
        return {"key": key, "updated": bool(row), "tags": tag_list}

    def delete(self, key: str) -> bool:
        with self._write():
            return self._db.execute("DELETE FROM memories WHERE key=?", (key,)).rowcount > 0

    # ---- reads ----

    def get(self, key: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM memories WHERE key=?", (key,)).fetchone()
        return _row(r) if r else None

    def list(self, tag: str | None = None, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM memories ORDER BY updated_at DESC"
            ).fetchall()
        items = [_row(r) for r in rows]
        if tag:
            items = [m for m in items if tag.strip().lower() in m["tags"]]
        return items[:limit]

    def search(self, query: str, limit: int = 5) -> tuple[list[dict], str]:
        """Hybrid search. Returns (results, mode) where mode is 'hybrid' or 'keyword'.

        Score = cosine similarity (meaning) + a small bonus for keyword hits (exact terms).
        Similarity leads; keywords break ties and rescue exact matches such as names or ids.
        """
        if not query.strip():
            return [], "keyword"
        kw = self._keyword_keys(query, limit * 4)
        bonus = {key: KEYWORD_BONUS / (1 + rank) for rank, key in enumerate(kw)}
        sims = self._similarities(query, limit * 4, extra=kw)
        mode = "hybrid"
        if sims is None:
            mode, sims = "keyword", {}
        scores = {k: sims.get(k, 0.0) + bonus.get(k, 0.0) for k in set(sims) | set(bonus)}
        out = []
        for key in sorted(scores, key=scores.get, reverse=True)[:limit]:
            m = self.get(key)
            if m:
                m["score"] = round(scores[key], 4)
                out.append(m)
        return out, mode

    def stats(self) -> dict:
        with self._lock:
            n = self._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            v = self._db.execute(
                "SELECT COUNT(*) FROM vectors WHERE model=?", (self.embedder.model,)
            ).fetchone()[0]
        size = self.path.stat().st_size if self.path.exists() else 0
        return {
            "memories": n,
            "embedded": v,
            "model": self.embedder.model,
            "db": str(self.path),
            "db_bytes": size,
        }

    def export(self) -> list[dict]:
        return self.list(limit=10**9)

    # ---- internals ----

    def _keyword_keys(self, query: str, limit: int) -> list[str]:
        terms = [t for t in re.findall(r"\w+", query.lower()) if t not in STOPWORDS]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        with self._lock:
            rows = self._db.execute(
                "SELECT key FROM memories_fts WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts) LIMIT ?",
                (match, limit),
            ).fetchall()
        return [r["key"] for r in rows]

    def _similarities(self, query: str, limit: int, extra: list[str] = ()) -> dict[str, float] | None:
        """Cosine similarity of the query to the top `limit` memories (plus `extra` keys).
        Returns None when the embedding model is unavailable."""
        try:
            self._embed_missing()
            q = self.embedder.embed([query])[0]
        except Exception as e:  # noqa: BLE001 - never let embeddings break search
            log.warning("semantic search unavailable, using keyword only: %s", e)
            return None
        keys, matrix = self._vector_matrix()
        if not keys:
            return {}
        sims = matrix @ q
        top = np.argsort(-sims)[:limit]
        out = {keys[i]: float(sims[i]) for i in top}
        if extra:
            index = {k: i for i, k in enumerate(keys)}
            out.update({k: float(sims[index[k]]) for k in extra if k in index})
        return out

    def _semantic_keys(self, query: str, limit: int) -> list[str] | None:
        sims = self._similarities(query, limit)
        return None if sims is None else sorted(sims, key=sims.get, reverse=True)

    def _vector_matrix(self) -> tuple[list[str], np.ndarray]:
        """All vectors for the current model, cached until the database changes
        (data_version bumps on commits from other processes; own writes clear it directly)."""
        with self._lock:
            stamp = (self.embedder.model, self._db.execute("PRAGMA data_version").fetchone()[0])
            if self._cache is None or self._cache[0] != stamp:
                rows = self._db.execute(
                    "SELECT key, vec FROM vectors WHERE model=?", (self.embedder.model,)
                ).fetchall()
                keys = [r["key"] for r in rows]
                matrix = (
                    np.vstack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
                    if rows
                    else np.empty((0, 0), dtype=np.float32)
                )
                self._cache = (stamp, keys, matrix)
            return self._cache[1], self._cache[2]

    def _embed_missing(self, only: list[str] | None = None) -> None:
        """Embed memories that have no vector for the current model (new, or model changed)."""
        with self._lock:
            sql = (
                "SELECT m.key, m.content, m.tags FROM memories m "
                "LEFT JOIN vectors v ON v.key=m.key AND v.model=? WHERE v.key IS NULL"
            )
            rows = self._db.execute(sql, (self.embedder.model,)).fetchall()
        rows = [r for r in rows if only is None or r["key"] in only]
        if not rows:
            return
        try:
            vecs = self.embedder.embed(
                [f"{r['key']}\n{r['content']}\n{' '.join(json.loads(r['tags']))}" for r in rows]
            )
        except Exception as e:  # noqa: BLE001
            if only is None:
                raise
            log.warning("could not embed %d memories yet: %s", len(rows), e)
            return
        with self._write():
            for r, v in zip(rows, vecs, strict=True):
                self._db.execute(
                    "INSERT OR REPLACE INTO vectors(key, model, vec) VALUES (?,?,?)",
                    (r["key"], self.embedder.model, v.tobytes()),
                )

    def close(self) -> None:
        with self._lock:
            self._db.close()
