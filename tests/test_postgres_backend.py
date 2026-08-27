from __future__ import annotations

import os

import pytest
from conftest import DeterministicProvider

from adaptive_memory_engine.engine import MemoryEngine

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL is not configured"
)


def test_postgres_crud_hybrid_search_and_restart(tmp_path) -> None:
    url = os.environ["TEST_POSTGRES_URL"]
    provider = DeterministicProvider()
    engine = MemoryEngine(
        provider,
        provider,
        data_dir=tmp_path,
        storage_backend="postgres",
        database_url=url,
    )
    engine.initialize()
    try:
        engine.store_memory("pg-alpha", "Bearer token authentication for the API", ["security"])
        engine.store_memory("pg-beta", "A recipe for sourdough bread", ["food"])
        assert engine.recall_memory("pg-alpha")["tags"] == ["security"]
        assert engine.search_memories("authentication", mode="keyword")[0]["memory"]["id"] == "pg-alpha"
        semantic = engine.search_memories("API security", mode="semantic")
        assert any(item["memory"]["id"] == "pg-alpha" for item in semantic)
        assert engine.get_stats()["chunks"] == 2
    finally:
        engine.close()

    restarted = MemoryEngine(
        provider,
        provider,
        data_dir=tmp_path,
        storage_backend="postgres",
        database_url=url,
    )
    restarted.initialize()
    try:
        assert restarted.recall_memory("pg-alpha") is not None
        assert restarted.search_memories("API security", mode="semantic")
        assert restarted.query_graph()["concepts"] > 0
        rebuilt = restarted.backfill_graph(rebuild_all=True)
        graph_counts = restarted.query_graph()
        rebuilt_again = restarted.backfill_graph(rebuild_all=True)
        assert rebuilt["applied"] is True
        assert rebuilt_again["applied"] is True
        assert restarted.query_graph()["concepts"] == graph_counts["concepts"]
        assert restarted.query_graph()["relationships"] == graph_counts["relationships"]
        assert restarted.delete_memory("pg-beta") is True
    finally:
        restarted.delete_memory("pg-alpha")
        restarted.close()
