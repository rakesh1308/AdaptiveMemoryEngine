"""Idempotent SQLite-backup to PostgreSQL/pgvector migration CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .chunking import ChunkingStrategies
from .config import Config
from .providers.factory import ProviderFactory
from .storage.postgres_backend import PostgresBackend

log = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _can_read_schema(path: Path) -> bool:
    try:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        return True
    except sqlite3.DatabaseError:
        return False


def recover_sqlite(source: Path, sqlite3_bin: str | None, work_dir: Path) -> tuple[Path, bool]:
    """Return a readable DB, using SQLite ``.recover`` without touching source."""
    if _can_read_schema(source):
        return source, False
    executable = sqlite3_bin or shutil.which("sqlite3")
    if not executable:
        raise RuntimeError(
            "SQLite backup is malformed and sqlite3 recovery CLI is unavailable; "
            "install sqlite3 or pass --sqlite3-bin"
        )
    recovered = work_dir / "recovered.db"
    producer = subprocess.Popen(  # noqa: S603 - executable is operator-selected
        [executable, str(source), ".recover"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert producer.stdout is not None
    consumer = subprocess.Popen(  # noqa: S603 - executable is operator-selected
        [executable, str(recovered)],
        stdin=producer.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    producer.stdout.close()
    _, consumer_error = consumer.communicate()
    producer.wait(timeout=300)
    assert producer.stderr is not None
    producer_error = producer.stderr.read()
    if producer.returncode or consumer.returncode or not _can_read_schema(recovered):
        error = (producer_error + consumer_error).decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"SQLite recovery failed: {error}")
    return recovered, True


def _rows(conn: sqlite3.Connection, query: str, batch_size: int) -> Iterator[sqlite3.Row]:
    cursor = conn.execute(query)
    while batch := cursor.fetchmany(batch_size):
        yield from batch


def _batches(
    conn: sqlite3.Connection, query: str, batch_size: int
) -> Iterator[list[sqlite3.Row]]:
    """Stream SQLite rows in bounded batches for efficient remote upserts."""
    cursor = conn.execute(query)
    while batch := cursor.fetchmany(batch_size):
        yield batch


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return default


def _embedding(blob: bytes | None) -> list[float] | None:
    if not blob or len(blob) % 4:
        return None
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _source_counts(conn: sqlite3.Connection) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in ("memories", "embeddings", "memory_versions", "memory_suggestions", "access_log"):
        result[table] = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] if _table_exists(conn, table) else 0
    return result


def _sqlite_content_digest(conn: sqlite3.Connection) -> str:
    row_hashes = []
    for row in conn.execute("SELECT id,content FROM memories"):
        payload = str(row["id"]).encode("utf-8") + b"\0" + str(row["content"]).encode("utf-8")
        row_hashes.append(hashlib.sha256(payload).digest())
    return hashlib.sha256(b"".join(sorted(row_hashes))).hexdigest()


def _postgres_content_digest(backend: PostgresBackend) -> str:
    row_hashes = []
    with backend.pool.connection() as conn:
        for row in conn.execute("SELECT id,content FROM memories"):
            payload = str(row["id"]).encode("utf-8") + b"\0" + str(row["content"]).encode("utf-8")
            row_hashes.append(hashlib.sha256(payload).digest())
    return hashlib.sha256(b"".join(sorted(row_hashes))).hexdigest()


def _detect_dimensions(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT embedding FROM embeddings WHERE embedding IS NOT NULL LIMIT 1").fetchone()
    vector = _embedding(row[0]) if row else None
    if not vector:
        raise RuntimeError("No valid stored embedding found; use --embedding-mode reembed")
    return len(vector)


def migrate(
    source_dir: Path,
    database_url: str,
    *,
    sqlite3_bin: str | None = None,
    batch_size: int = 100,
    embedding_mode: str = "stored",
    force: bool = False,
) -> dict[str, Any]:
    source_db = source_dir / "memories.db"
    if not source_db.is_file():
        raise FileNotFoundError(f"Backup database not found: {source_db}")
    source_hash = _sha256(source_db)
    if not force:
        try:
            with psycopg.connect(database_url, row_factory=dict_row) as target:
                completed = target.execute(
                    "SELECT status,source_counts,destination_counts FROM migration_runs WHERE source_sha256=%s",
                    (source_hash,),
                ).fetchone()
            if completed and completed["status"] == "complete":
                return {
                    "status": "already_complete",
                    "sourceSha256": source_hash,
                    "sourceCounts": completed["source_counts"],
                    "destinationCounts": completed["destination_counts"],
                }
        except psycopg.Error:
            # Fresh database: schema and migration_runs do not exist yet.
            pass
    with tempfile.TemporaryDirectory(prefix="ame-migrate-") as temporary:
        readable_db, recovered = recover_sqlite(source_db, sqlite3_bin, Path(temporary))
        source = sqlite3.connect(f"file:{readable_db.as_posix()}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        counts = _source_counts(source)
        provider = None
        intelligence_provider = None
        if embedding_mode == "stored":
            dimensions = _detect_dimensions(source)
        elif embedding_mode == "reembed":
            cfg = Config.load()
            provider, intelligence_provider = ProviderFactory.create(cfg)
            dimensions = int(getattr(provider, "dimensions", cfg.embedding_dims))
        else:
            raise ValueError("embedding_mode must be 'stored' or 'reembed'")

        backend = PostgresBackend(database_url, dimensions=dimensions)
        backend.initialize()
        failures: list[dict[str, str]] = []
        with psycopg.connect(database_url, row_factory=dict_row) as target:
            existing = target.execute(
                "SELECT status FROM migration_runs WHERE source_sha256=%s", (source_hash,)
            ).fetchone()
            if existing and existing["status"] == "complete" and not force:
                backend.close()
                source.close()
                return {"status": "already_complete", "sourceSha256": source_hash, "sourceCounts": counts}
            target.execute(
                """INSERT INTO migration_runs(source_sha256,source_path,status,source_counts,error)
                VALUES(%s,%s,'running',%s,NULL) ON CONFLICT(source_sha256) DO UPDATE
                SET status='running',source_counts=excluded.source_counts,error=NULL,started_at=now(),completed_at=NULL""",
                (source_hash, str(source_db), Jsonb(counts)),
            )
            target.commit()

        memory_upsert = """INSERT INTO memories
            (id,content,tags,created_at,updated_at,importance,strength,access_count,source,version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET content=excluded.content,tags=excluded.tags,
            updated_at=excluded.updated_at,importance=excluded.importance,
            strength=excluded.strength,access_count=excluded.access_count,
            source=excluded.source,version=excluded.version"""
        with backend.pool.connection() as target:
            for batch in _batches(source, "SELECT * FROM memories ORDER BY rowid", batch_size):
                parameters = [
                    (
                        row["id"], row["content"], Jsonb(_json(row["tags"], [])),
                        row["created_at"], row["updated_at"], row["importance"],
                        row["strength"], row["access_count"], row["source"], row["version"],
                    )
                    for row in batch
                ]
                try:
                    with target.transaction():
                        target.cursor().executemany(memory_upsert, parameters)
                except psycopg.Error:
                    # Preserve per-record diagnostics if a single legacy row is invalid.
                    for row, values in zip(batch, parameters, strict=True):
                        try:
                            with target.transaction():
                                target.execute(memory_upsert, values)
                        except psycopg.Error as exc:
                            failures.append({
                                "table": "memories", "id": str(row["id"]),
                                "error": type(exc).__name__,
                            })

        with backend.pool.connection() as target:
            if _table_exists(source, "memory_versions"):
                for row in _rows(source, "SELECT * FROM memory_versions", batch_size):
                    target.execute(
                        """INSERT INTO memory_versions(version_id,memory_id,content,tags,importance,version_num,created_at,source)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(version_id) DO NOTHING""",
                        (row["version_id"], row["memory_id"], row["content"], Jsonb(_json(row["tags"], [])), row["importance"], row["version_num"], row["created_at"], row["source"]),
                    )
            if _table_exists(source, "access_log"):
                for row in _rows(source, "SELECT * FROM access_log", batch_size):
                    target.execute(
                        """INSERT INTO access_log(id,memory_id,accessed_at,context)
                        SELECT %s,%s,%s,%s WHERE EXISTS(SELECT 1 FROM memories WHERE id=%s)
                        ON CONFLICT(id) DO NOTHING""",
                        (row["id"], row["memory_id"], row["accessed_at"], Jsonb(_json(row["context"], {})), row["memory_id"]),
                    )
            if _table_exists(source, "memory_suggestions"):
                for row in _rows(source, "SELECT * FROM memory_suggestions", batch_size):
                    target.execute(
                        """INSERT INTO memory_suggestions(suggestion_id,kind,status,target_ids,summary,payload,created_at,resolved_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(suggestion_id) DO NOTHING""",
                        (row["suggestion_id"], row["kind"], row["status"], Jsonb(_json(row["target_ids"], [])), row["summary"], Jsonb(_json(row["payload"], {})), row["created_at"], row["resolved_at"]),
                    )

        if embedding_mode == "stored":
            query = "SELECT e.memory_id,e.embedding,m.content FROM embeddings e JOIN memories m ON m.id=e.memory_id ORDER BY e.memory_id"
            embedding_upsert = """INSERT INTO embeddings(memory_id,embedding)
                VALUES(%s,%s) ON CONFLICT(memory_id) DO UPDATE SET
                embedding=excluded.embedding,updated_at=now()"""
            chunk_upsert = """INSERT INTO chunks
                (id,memory_id,chunk_index,content,content_hash,embedding,embedding_model,metadata)
                VALUES(%s,%s,0,%s,%s,%s,'legacy-stored',%s)
                ON CONFLICT(id) DO UPDATE SET content=excluded.content,
                content_hash=excluded.content_hash,embedding=excluded.embedding,
                embedding_model=excluded.embedding_model,metadata=excluded.metadata"""
            with backend.pool.connection() as target:
                for batch in _batches(source, query, batch_size):
                    valid: list[tuple[sqlite3.Row, list[float]]] = []
                    for row in batch:
                        vector = _embedding(row["embedding"])
                        if not vector or len(vector) != dimensions:
                            failures.append({
                                "table": "embeddings", "id": str(row["memory_id"]),
                                "error": "invalid_dimensions",
                            })
                            continue
                        valid.append((row, vector))
                    if not valid:
                        continue
                    memory_ids = [str(row["memory_id"]) for row, _ in valid]
                    embedding_parameters = [
                        (row["memory_id"], vector) for row, vector in valid
                    ]
                    chunk_parameters = [
                        (
                            f"{row['memory_id']}__0", row["memory_id"], row["content"],
                            hashlib.sha256(row["content"].encode()).hexdigest(), vector,
                            Jsonb({"start": 0, "end": len(row["content"])}),
                        )
                        for row, vector in valid
                    ]
                    try:
                        with target.transaction():
                            target.execute("DELETE FROM chunks WHERE memory_id = ANY(%s)", (memory_ids,))
                            target.cursor().executemany(embedding_upsert, embedding_parameters)
                            target.cursor().executemany(chunk_upsert, chunk_parameters)
                    except psycopg.Error:
                        # A bad vector should not prevent other recoverable rows from loading.
                        for row, vector in valid:
                            try:
                                backend.save_embedding(row["memory_id"], vector)
                                backend.save_chunks(
                                    row["memory_id"],
                                    [{"content": row["content"], "start": 0, "end": len(row["content"])}],
                                    [vector],
                                    "legacy-stored",
                                )
                            except psycopg.Error as exc:
                                failures.append({
                                    "table": "embeddings", "id": str(row["memory_id"]),
                                    "error": type(exc).__name__,
                                })
        else:
            assert provider is not None
            model_config = provider.get_config()
            model = str(model_config.get("model") or model_config.get("embeddingModel") or "configured")
            for row in _rows(source, "SELECT id,content FROM memories ORDER BY rowid", batch_size):
                try:
                    chunks = ChunkingStrategies.semantic(row["content"])
                    vectors = provider.embed_batch([chunk["content"] for chunk in chunks])
                    backend.save_chunks(row["id"], chunks, vectors, model)
                    backend.save_embedding(row["id"], vectors[-1])
                except Exception as exc:  # noqa: BLE001
                    failures.append({"table": "chunks", "id": str(row["id"]), "error": type(exc).__name__})

        destination = backend.get_stats()
        with backend.pool.connection() as target:
            destination["memory_versions"] = target.execute("SELECT count(*) n FROM memory_versions").fetchone()["n"]
            destination["access_log"] = target.execute("SELECT count(*) n FROM access_log").fetchone()["n"]
            destination["memory_suggestions"] = target.execute("SELECT count(*) n FROM memory_suggestions").fetchone()["n"]
        source_content_hash = _sqlite_content_digest(source)
        destination_content_hash = _postgres_content_digest(backend)
        content_hash_match = source_content_hash == destination_content_hash
        relational_counts_match = all(
            destination.get(target_name) == counts[source_name]
            for source_name, target_name in (
                ("memories", "total"),
                ("memory_versions", "memory_versions"),
                ("memory_suggestions", "memory_suggestions"),
                ("access_log", "access_log"),
            )
        )
        status = "complete" if relational_counts_match and content_hash_match and not failures else "failed"
        report = {
            "status": status, "sourceSha256": source_hash, "sourceRecovered": recovered,
            "sourceCounts": counts, "destinationCounts": destination,
            "embeddingMode": embedding_mode, "dimensions": dimensions,
            "failures": failures[:100], "failureCount": len(failures),
            "sourceContentSha256": source_content_hash,
            "destinationContentSha256": destination_content_hash,
            "contentHashMatch": content_hash_match,
            "graphAction": "rebuild_required_from_memories",
        }
        with backend.pool.connection() as target:
            target.execute(
                "UPDATE migration_runs SET status=%s,destination_counts=%s,completed_at=now(),error=%s WHERE source_sha256=%s",
                (status, Jsonb(destination), None if status == "complete" else json.dumps(failures[:20]), source_hash),
            )
        providers = {
            id(item): item
            for item in (provider, intelligence_provider)
            if item is not None
        }
        for item in providers.values():
            close = getattr(item, "close", None)
            if close:
                close()
        backend.close()
        source.close()
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--sqlite3-bin")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--embedding-mode", choices=("stored", "reembed"), default="stored")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    database_url = args.database_url or Config.load().database_url
    if not database_url:
        parser.error("--database-url or DATABASE_URL is required")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    report = migrate(args.source_dir.resolve(), database_url, sqlite3_bin=args.sqlite3_bin, batch_size=max(1, args.batch_size), embedding_mode=args.embedding_mode, force=args.force)
    print(json.dumps(report, indent=2))
    if report["status"] not in {"complete", "already_complete"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
