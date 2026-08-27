from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from adaptive_memory_engine.lifecycle import ImportanceScorer
from adaptive_memory_engine.providers.base import EmbeddingProvider


def test_update_removes_stale_chunks_vectors_and_graph_evidence(engine):
    long_content = "Old Concept\n\n" + ("first section " * 700)
    engine.store_memory("doc", long_content, tags=["old-tag"])
    old_vector_ids = {key for key in engine.vector_store.vectors if key.startswith("doc__")}
    assert len(old_vector_ids) > 1
    assert "old_concept" in engine.knowledge_graph.concepts

    engine.update_memory("doc", content="New Concept replaces the prior text.", tags=["new-tag"])

    new_vector_ids = {key for key in engine.vector_store.vectors if key.startswith("doc__")}
    assert new_vector_ids == {"doc__0"}
    assert "old_concept" not in engine.knowledge_graph.concepts
    assert "new_concept" in engine.knowledge_graph.concepts


def test_concurrent_writes_remain_consistent(engine):
    def write(index: int) -> None:
        engine.store_memory(f"key-{index}", f"Concurrent Memory {index}", tags=["load"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(30)))

    assert engine.get_stats()["total"] == 30
    assert len(engine.list_memories(limit=100)) == 30
    assert engine.sqlite.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_input_limits_are_enforced(engine):
    with pytest.raises(ValueError, match="non-empty"):
        engine.store_memory("", "content")
    with pytest.raises(ValueError, match="1 MB"):
        engine.store_memory("large", "x" * 1_000_001)
    with pytest.raises(ValueError, match="at most 50 tags"):
        engine.store_memory("tags", "content", tags=[f"t{i}" for i in range(51)])


def test_failed_update_embedding_never_reuses_stale_vector(engine):
    class FailingProvider(EmbeddingProvider):
        def is_available(self) -> bool:
            return True

        def embed(self, text: str) -> list[float]:
            raise RuntimeError("provider unavailable")

    engine.store_memory("changing", "Old searchable content")
    assert engine.sqlite.get_embedding("changing") is not None

    engine.embedding_provider = FailingProvider()
    engine.update_memory("changing", content="Completely new content")

    assert engine.sqlite.get_embedding("changing") is None
    assert not any(key.startswith("changing") for key in engine.vector_store.vectors)


def test_recency_score_decays_in_days():
    scorer = ImportanceScorer()
    now = datetime.now(UTC)
    recent = scorer.calculate({"content": "same", "updatedAt": now.isoformat()})
    old = scorer.calculate(
        {"content": "same", "updatedAt": (now - timedelta(days=365)).isoformat()}
    )
    assert old < recent


def test_full_graph_rebuild_is_a_stable_replacement(engine):
    engine.store_memory("graph-a", "Alpha Project uses PostgreSQL", tags=["database"])
    engine.store_memory("graph-b", "Alpha Project uses Python", tags=["database"])

    first = engine.backfill_graph(rebuild_all=True)
    first_frequencies = {
        key: node["frequency"] for key, node in engine.knowledge_graph.concepts.items()
    }
    first_relationships = len(engine.knowledge_graph.relationships)

    second = engine.backfill_graph(rebuild_all=True)
    second_frequencies = {
        key: node["frequency"] for key, node in engine.knowledge_graph.concepts.items()
    }

    assert first["applied"] is True
    assert second["applied"] is True
    assert second_frequencies == first_frequencies
    assert len(engine.knowledge_graph.relationships) == first_relationships
