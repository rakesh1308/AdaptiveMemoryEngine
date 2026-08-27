"""PostgreSQL 18 + pgvector production storage backend."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ..events import now_iso


class PostgresBackend:
    """Authoritative relational, lexical, and vector store.

    The API intentionally mirrors ``SQLiteBackend`` so MCP/REST contracts remain
    stable while the production persistence implementation changes completely.
    """

    loads_application_cache = False

    def __init__(
        self,
        database_url: str,
        dimensions: int,
        pool_min: int = 1,
        pool_max: int = 10,
    ) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        if not 1 <= dimensions <= 2_000:
            raise ValueError("HNSW vector dimensions must be between 1 and 2000")
        self.database_url = database_url
        self.dimensions = dimensions
        self.pool_min = pool_min
        self.pool_max = pool_max
        self._pool: ConnectionPool | None = None

    @property
    def pool(self) -> ConnectionPool:
        if self._pool is None:
            raise RuntimeError("PostgresBackend not initialized")
        return self._pool

    def initialize(self) -> None:
        schema = f"""
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE IF NOT EXISTS memories (
          id TEXT PRIMARY KEY,
          content TEXT NOT NULL,
          tags JSONB NOT NULL DEFAULT '[]'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          importance INTEGER NOT NULL DEFAULT 50,
          strength DOUBLE PRECISION NOT NULL DEFAULT 1.0,
          access_count INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL DEFAULT 'user',
          version INTEGER NOT NULL DEFAULT 1,
          search_vector TSVECTOR GENERATED ALWAYS AS
            (to_tsvector('simple', coalesce(id, '') || ' ' || coalesce(content, '') || ' ' || coalesce(tags::text, ''))) STORED
        );
        CREATE INDEX IF NOT EXISTS memories_search_idx ON memories USING GIN(search_vector);
        CREATE INDEX IF NOT EXISTS memories_tags_idx ON memories USING GIN(tags);
        CREATE INDEX IF NOT EXISTS memories_updated_idx ON memories(updated_at DESC);

        CREATE TABLE IF NOT EXISTS embeddings (
          memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
          embedding vector({self.dimensions}) NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS chunks (
          id TEXT PRIMARY KEY,
          memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
          chunk_index INTEGER NOT NULL,
          content TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          embedding vector({self.dimensions}) NOT NULL,
          embedding_model TEXT NOT NULL,
          metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(memory_id, chunk_index)
        );
        CREATE INDEX IF NOT EXISTS chunks_memory_idx ON chunks(memory_id);
        CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
          ON chunks USING hnsw (embedding vector_cosine_ops);

        CREATE TABLE IF NOT EXISTS access_log (
          id BIGSERIAL PRIMARY KEY,
          memory_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
          accessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          context JSONB NOT NULL DEFAULT '{{}}'::jsonb
        );
        CREATE INDEX IF NOT EXISTS access_log_memory_idx ON access_log(memory_id, accessed_at DESC);
        CREATE TABLE IF NOT EXISTS memory_versions (
          version_id TEXT PRIMARY KEY,
          memory_id TEXT NOT NULL,
          content TEXT NOT NULL,
          tags JSONB NOT NULL DEFAULT '[]'::jsonb,
          importance INTEGER NOT NULL DEFAULT 50,
          version_num INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          source TEXT NOT NULL DEFAULT 'mcp'
        );
        CREATE INDEX IF NOT EXISTS versions_memory_idx ON memory_versions(memory_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS memory_suggestions (
          suggestion_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          status TEXT NOT NULL,
          target_ids JSONB NOT NULL,
          summary TEXT NOT NULL,
          payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS suggestions_status_idx ON memory_suggestions(status, created_at DESC);
        CREATE TABLE IF NOT EXISTS migration_runs (
          source_sha256 TEXT PRIMARY KEY,
          source_path TEXT NOT NULL,
          status TEXT NOT NULL,
          source_counts JSONB NOT NULL DEFAULT '{{}}'::jsonb,
          destination_counts JSONB NOT NULL DEFAULT '{{}}'::jsonb,
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          error TEXT
        );
        CREATE TABLE IF NOT EXISTS graph_concepts (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          frequency INTEGER NOT NULL DEFAULT 0,
          centrality DOUBLE PRECISION NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS graph_concept_memories (
          concept_id TEXT NOT NULL REFERENCES graph_concepts(id) ON DELETE CASCADE,
          memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
          PRIMARY KEY(concept_id,memory_id)
        );
        CREATE INDEX IF NOT EXISTS graph_concept_memory_idx ON graph_concept_memories(memory_id);
        CREATE TABLE IF NOT EXISTS graph_relationships (
          id TEXT PRIMARY KEY,
          from_concept TEXT NOT NULL REFERENCES graph_concepts(id) ON DELETE CASCADE,
          to_concept TEXT NOT NULL REFERENCES graph_concepts(id) ON DELETE CASCADE,
          type TEXT NOT NULL,
          strength DOUBLE PRECISION NOT NULL DEFAULT 0.5,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS graph_relationship_evidence (
          relationship_id TEXT NOT NULL REFERENCES graph_relationships(id) ON DELETE CASCADE,
          memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
          PRIMARY KEY(relationship_id,memory_id)
        );
        CREATE INDEX IF NOT EXISTS graph_evidence_memory_idx ON graph_relationship_evidence(memory_id);
        """
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            conn.execute(schema)
            row = conn.execute(
                "SELECT vector_dims(embedding) AS dimensions FROM chunks LIMIT 1"
            ).fetchone()
            if row and int(row[0]) != self.dimensions:
                raise RuntimeError(
                    f"database vectors use {row[0]} dimensions but provider uses {self.dimensions}; "
                    "run a re-embedding migration into a new database"
                )
        self._pool = ConnectionPool(
            self.database_url,
            min_size=self.pool_min,
            max_size=self.pool_max,
            kwargs={"row_factory": dict_row},
            configure=register_vector,
            open=True,
        )
        self._pool.wait(timeout=30)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    @staticmethod
    def _memory(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        d["tags"] = list(d.get("tags") or [])
        for source, target in (("created_at", "createdAt"), ("updated_at", "updatedAt")):
            value = d.pop(source, None)
            d[target] = value.isoformat() if hasattr(value, "isoformat") else value
        d["accessCount"] = d.pop("access_count", 0)
        d.pop("search_vector", None)
        d.pop("text_rank", None)
        return d

    def insert(self, memory: dict[str, Any]) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """INSERT INTO memories
                (id,content,tags,created_at,updated_at,importance,strength,access_count,source,version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET content=excluded.content,tags=excluded.tags,
                updated_at=excluded.updated_at,importance=excluded.importance,strength=excluded.strength,
                access_count=excluded.access_count,source=excluded.source,version=excluded.version""",
                (
                    memory["id"], memory["content"], Jsonb(memory.get("tags", [])),
                    memory.get("createdAt") or now_iso(), memory.get("updatedAt") or now_iso(),
                    int(memory.get("importance", 50)), float(memory.get("strength", 1.0)),
                    int(memory.get("accessCount", 0)), memory.get("source", "user"),
                    int(memory.get("version", 1)),
                ),
            )

    def get(self, memory_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            return self._memory(conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone())

    def get_all(self) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC").fetchall()
        return [m for row in rows if (m := self._memory(row)) is not None]

    def get_many(self, memory_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not memory_ids:
            return {}
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT * FROM memories WHERE id=ANY(%s)", (memory_ids,)).fetchall()
        memories = [m for row in rows if (m := self._memory(row)) is not None]
        return {memory["id"]: memory for memory in memories}

    def delete(self, memory_id: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM memories WHERE id=%s", (memory_id,))
            conn.execute("DELETE FROM memory_versions WHERE memory_id=%s", (memory_id,))

    def update(self, memory_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        columns = {"content": "content", "tags": "tags", "importance": "importance", "strength": "strength", "accessCount": "access_count"}
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            column = columns.get(key)
            if column:
                assignments.append(f"{column}=%s")
                values.append(Jsonb(value) if key == "tags" else value)
        if not assignments:
            return self.get(memory_id)
        assignments.append("updated_at=now()")
        values.append(memory_id)
        with self.pool.connection() as conn:
            conn.execute(f"UPDATE memories SET {','.join(assignments)} WHERE id=%s", values)
        return self.get(memory_id)

    def search_keyword(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                """SELECT *, ts_rank_cd(search_vector, websearch_to_tsquery('simple', %s)) AS text_rank
                FROM memories WHERE search_vector @@ websearch_to_tsquery('simple', %s)
                ORDER BY text_rank DESC, updated_at DESC LIMIT %s""",
                (query, query, limit),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE content ILIKE %s OR id ILIKE %s ORDER BY updated_at DESC LIMIT %s",
                    (f"%{query}%", f"%{query}%", limit),
                ).fetchall()
        return [m for row in rows if (m := self._memory(row)) is not None]

    def get_by_tag(self, tag: str) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT * FROM memories WHERE tags @> %s ORDER BY updated_at DESC", (Jsonb([tag]),)).fetchall()
        return [m for row in rows if (m := self._memory(row)) is not None]

    def save_embedding(self, memory_id: str, embedding: list[float]) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO embeddings(memory_id,embedding) VALUES(%s,%s) ON CONFLICT(memory_id) DO UPDATE SET embedding=excluded.embedding,updated_at=now()",
                (memory_id, embedding),
            )

    def delete_embedding(self, memory_id: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM embeddings WHERE memory_id=%s", (memory_id,))
            conn.execute("DELETE FROM chunks WHERE memory_id=%s", (memory_id,))

    def get_embedding(self, memory_id: str) -> list[float] | None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT embedding FROM embeddings WHERE memory_id=%s", (memory_id,)).fetchone()
        return list(row["embedding"]) if row else None

    def get_all_embeddings(self) -> OrderedDict[str, list[float]]:
        return OrderedDict()

    def save_chunks(self, memory_id: str, chunks: list[dict], embeddings: list[list[float]], model: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM chunks WHERE memory_id=%s", (memory_id,))
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
                content = chunk["content"]
                conn.execute(
                    """INSERT INTO chunks(id,memory_id,chunk_index,content,content_hash,embedding,embedding_model,metadata)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (f"{memory_id}__{index}", memory_id, index, content,
                     __import__("hashlib").sha256(content.encode()).hexdigest(), embedding, model,
                     Jsonb({"start": chunk.get("start", 0), "end": chunk.get("end", 0)})),
                )

    def search_vectors(self, vector: list[float], limit: int) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute(
                """SELECT id,memory_id,chunk_index,1-(embedding <=> %s::vector) AS score
                FROM chunks ORDER BY embedding <=> %s::vector LIMIT %s""",
                (vector, vector, limit),
            ).fetchall()

    def record_access(self, memory_id: str, context: dict | None = None) -> None:
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("INSERT INTO access_log(memory_id,context) VALUES(%s,%s)", (memory_id, Jsonb(context or {})))
            conn.execute("UPDATE memories SET access_count=access_count+1 WHERE id=%s", (memory_id,))

    def get_stats(self) -> dict[str, int]:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT count(*) total,(SELECT count(*) FROM embeddings) embeddings,(SELECT count(*) FROM chunks) chunks FROM memories").fetchone()
        return {"total": row["total"], "withEmbeddings": row["embeddings"], "chunks": row["chunks"]}

    def snapshot_version(self, memory: dict[str, Any]) -> str:
        version_id = str(uuid.uuid4())
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO memory_versions(version_id,memory_id,content,tags,importance,version_num,source) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (version_id, memory["id"], memory.get("content", ""), Jsonb(memory.get("tags", [])), int(memory.get("importance", 50)), int(memory.get("version", 1)), memory.get("source", "user")),
            )
        return version_id

    @staticmethod
    def _version(row: dict[str, Any]) -> dict[str, Any]:
        d = dict(row)
        d["tags"] = list(d.get("tags") or [])
        value = d.pop("created_at", None)
        d["createdAt"] = value.isoformat() if hasattr(value, "isoformat") else value
        return d

    def get_versions(self, memory_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT * FROM memory_versions WHERE memory_id=%s ORDER BY created_at DESC LIMIT %s", (memory_id, limit)).fetchall()
        return [self._version(row) for row in rows]

    def get_version(self, version_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT * FROM memory_versions WHERE version_id=%s", (version_id,)).fetchone()
        return self._version(row) if row else None

    def create_suggestion(self, kind: str, target_ids: list[str], summary: str, payload: dict | None = None) -> str:
        sid = str(uuid.uuid4())
        with self.pool.connection() as conn:
            conn.execute("INSERT INTO memory_suggestions(suggestion_id,kind,status,target_ids,summary,payload) VALUES(%s,%s,'open',%s,%s,%s)", (sid, kind, Jsonb(target_ids), summary, Jsonb(payload or {})))
        return sid

    @staticmethod
    def _suggestion(row: dict[str, Any]) -> dict[str, Any]:
        d = dict(row)
        d["target_ids"] = list(d.get("target_ids") or [])
        d["payload"] = dict(d.get("payload") or {})
        for source, target in (("created_at", "createdAt"), ("resolved_at", "resolvedAt")):
            value = d.pop(source, None)
            d[target] = value.isoformat() if hasattr(value, "isoformat") else value
        return d

    def list_suggestions(self, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT * FROM memory_suggestions WHERE status=%s ORDER BY created_at DESC LIMIT %s", (status, limit)).fetchall()
        return [self._suggestion(row) for row in rows]

    def get_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT * FROM memory_suggestions WHERE suggestion_id=%s", (suggestion_id,)).fetchone()
        return self._suggestion(row) if row else None

    def resolve_suggestion(self, suggestion_id: str, status: str) -> bool:
        if status not in {"applied", "dismissed"}:
            raise ValueError("invalid suggestion status")
        with self.pool.connection() as conn:
            result = conn.execute("UPDATE memory_suggestions SET status=%s,resolved_at=now() WHERE suggestion_id=%s AND status='open'", (status, suggestion_id))
        return result.rowcount > 0

    def list_stale(self, days: int = 180, limit: int = 20) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute(
                """SELECT m.id,m.content,max(a.accessed_at) last_seen FROM memories m
                LEFT JOIN access_log a ON a.memory_id=m.id GROUP BY m.id
                HAVING max(a.accessed_at) IS NULL OR max(a.accessed_at) < now()-(%s * interval '1 day') LIMIT %s""",
                (days, limit),
            ).fetchall()

    def health(self) -> dict[str, Any]:
        started = datetime.now(UTC)
        with self.pool.connection(timeout=5) as conn:
            conn.execute("SELECT 1").fetchone()
        return {"ok": True, "backend": "postgres-pgvector", "latencyMs": round((datetime.now(UTC)-started).total_seconds()*1000, 2)}

    def load_graph(self) -> tuple[dict[str, dict], list[dict], dict[str, set[str]]]:
        concepts: dict[str, dict] = {}
        concept_index: dict[str, set[str]] = {}
        relationships: list[dict] = []
        with self.pool.connection() as conn:
            for row in conn.execute("SELECT * FROM graph_concepts"):
                concepts[row["id"]] = {
                    "id": row["id"], "name": row["name"], "frequency": row["frequency"],
                    "memoryIds": [], "relatedConcepts": {}, "centrality": row["centrality"],
                    "createdAt": row["created_at"].isoformat(),
                }
            for row in conn.execute("SELECT concept_id,memory_id FROM graph_concept_memories"):
                concept_index.setdefault(row["concept_id"], set()).add(row["memory_id"])
                if row["concept_id"] in concepts:
                    concepts[row["concept_id"]]["memoryIds"].append(row["memory_id"])
            evidence: dict[str, list[str]] = {}
            for row in conn.execute("SELECT relationship_id,memory_id FROM graph_relationship_evidence"):
                evidence.setdefault(row["relationship_id"], []).append(row["memory_id"])
            for row in conn.execute("SELECT * FROM graph_relationships"):
                relationship = {
                    "id": row["id"], "from": row["from_concept"], "to": row["to_concept"],
                    "type": row["type"], "strength": row["strength"],
                    "evidence": evidence.get(row["id"], []), "createdAt": row["created_at"].isoformat(),
                }
                relationships.append(relationship)
                for left, right in ((row["from_concept"], row["to_concept"]), (row["to_concept"], row["from_concept"])):
                    if left in concepts:
                        concepts[left]["relatedConcepts"][right] = row["strength"]
        return concepts, relationships, concept_index

    def replace_graph(
        self,
        concepts: dict[str, dict],
        relationships: list[dict],
        concept_index: dict[str, set[str]],
    ) -> None:
        """Atomically replace all normalized graph state using PostgreSQL COPY."""
        with self.pool.connection() as conn, conn.transaction():
            conn.execute(
                "TRUNCATE graph_relationship_evidence, graph_relationships, "
                "graph_concept_memories, graph_concepts"
            )
            with conn.cursor().copy(
                "COPY graph_concepts(id,name,frequency,centrality,created_at) FROM STDIN"
            ) as copy:
                for concept_id, node in concepts.items():
                    copy.write_row((
                        concept_id,
                        node.get("name", concept_id),
                        int(node.get("frequency", 0)),
                        float(node.get("centrality", 0)),
                        node.get("createdAt") or now_iso(),
                    ))
            with conn.cursor().copy(
                "COPY graph_concept_memories(concept_id,memory_id) FROM STDIN"
            ) as copy:
                for concept_id, memory_ids in concept_index.items():
                    for memory_id in memory_ids:
                        copy.write_row((concept_id, memory_id))
            with conn.cursor().copy(
                "COPY graph_relationships"
                "(id,from_concept,to_concept,type,strength,created_at) FROM STDIN"
            ) as copy:
                for relationship in relationships:
                    copy.write_row((
                        relationship["id"],
                        relationship["from"],
                        relationship["to"],
                        relationship["type"],
                        float(relationship.get("strength", 0.5)),
                        relationship.get("createdAt") or now_iso(),
                    ))
            with conn.cursor().copy(
                "COPY graph_relationship_evidence(relationship_id,memory_id) FROM STDIN"
            ) as copy:
                for relationship in relationships:
                    for memory_id in relationship.get("evidence", []):
                        copy.write_row((relationship["id"], memory_id))

    def upsert_graph_concept(self, node: dict, memory_id: str | None) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """INSERT INTO graph_concepts(id,name,frequency,centrality,created_at)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,frequency=excluded.frequency,centrality=excluded.centrality""",
                (node["id"], node.get("name", node["id"]), int(node.get("frequency", 0)), float(node.get("centrality", 0)), node.get("createdAt") or now_iso()),
            )
            if memory_id:
                conn.execute("INSERT INTO graph_concept_memories(concept_id,memory_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (node["id"], memory_id))

    def upsert_graph_relationship(self, relationship: dict) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """INSERT INTO graph_relationships(id,from_concept,to_concept,type,strength,created_at)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET strength=excluded.strength,type=excluded.type""",
                (relationship["id"], relationship["from"], relationship["to"], relationship["type"], float(relationship.get("strength", 0.5)), relationship.get("createdAt") or now_iso()),
            )
            for memory_id in relationship.get("evidence", []):
                conn.execute(
                    """INSERT INTO graph_relationship_evidence(relationship_id,memory_id)
                    SELECT %s,%s WHERE EXISTS(SELECT 1 FROM memories WHERE id=%s) ON CONFLICT DO NOTHING""",
                    (relationship["id"], memory_id, memory_id),
                )

    def delete_graph_memory(self, memory_id: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM graph_relationship_evidence WHERE memory_id=%s", (memory_id,))
            conn.execute("DELETE FROM graph_concept_memories WHERE memory_id=%s", (memory_id,))
            conn.execute("DELETE FROM graph_relationships r WHERE NOT EXISTS(SELECT 1 FROM graph_relationship_evidence e WHERE e.relationship_id=r.id)")
            conn.execute("DELETE FROM graph_concepts c WHERE NOT EXISTS(SELECT 1 FROM graph_concept_memories m WHERE m.concept_id=c.id)")
