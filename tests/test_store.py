import hashlib

import numpy as np
import pytest

from adaptive_memory.embedder import Embedder
from adaptive_memory.store import MemoryStore


class FakeEmbedder(Embedder):
    """Bag-of-words hashing embedder: deterministic, no model download."""

    def __init__(self):
        super().__init__(model="fake")

    def embed(self, texts):
        out = np.zeros((len(texts), 64), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().split():
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
        n = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(n == 0, 1, n)


class BrokenEmbedder(Embedder):
    def embed(self, texts):
        raise RuntimeError("model unavailable")


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "m.db", FakeEmbedder())
    yield s
    s.close()


def test_store_get_update_delete(store):
    assert store.store("a/b", "first", ["X"])["updated"] is False
    assert store.get("a/b")["tags"] == ["x"]
    assert store.store("a/b", "second")["updated"] is True
    assert store.get("a/b")["content"] == "second"
    assert store.delete("a/b") and store.get("a/b") is None
    assert not store.delete("a/b")


def test_empty_rejected(store):
    with pytest.raises(ValueError):
        store.store("k", "  ")


def test_search_finds_relevant(store):
    store.store("db", "we chose postgres with pgvector for storage")
    store.store("ui", "the button color is blue")
    results, mode = store.search("postgres storage")
    assert mode == "hybrid" and results[0]["key"] == "db"


def test_search_survives_odd_query(store):
    store.store("k", "hello world")
    store.search('"; DROP TABLE memories; --')
    assert store.search("   ")[0] == []
    assert store.get("k") is not None


def test_update_reindexes_keyword_and_vector(store):
    store.store("k", "apples")
    store.store("k", "bananas")
    assert store.search("apples")[0] == [] or store.search("apples")[0][0]["content"] == "bananas"
    assert store.search("bananas")[0][0]["key"] == "k"
    assert store.stats()["embedded"] == 1


def test_keyword_fallback_when_embeddings_fail(tmp_path):
    s = MemoryStore(tmp_path / "m.db", BrokenEmbedder(model="broken"))
    s.store("k", "deploy with docker")  # must not raise
    results, mode = s.search("docker")
    assert mode == "keyword" and results[0]["key"] == "k"
    s.close()


def test_model_change_reembeds(tmp_path):
    s = MemoryStore(tmp_path / "m.db", FakeEmbedder())
    s.store("k", "hello")
    s.embedder.model = "fake2"
    assert s.stats()["embedded"] == 0
    s.search("hello")
    assert s.stats()["embedded"] == 1
    s.close()


def test_list_and_tag_filter(store):
    store.store("a", "one", ["t1"])
    store.store("b", "two", ["t2"])
    assert [m["key"] for m in store.list_memories(tag="t1")] == ["a"]
    assert len(store.export()) == 2


def test_cache_sees_writes_from_another_process(tmp_path):
    a = MemoryStore(tmp_path / "m.db", FakeEmbedder())
    b = MemoryStore(tmp_path / "m.db", FakeEmbedder())
    a.store("one", "postgres vector search")
    assert a.search("postgres")[0][0]["key"] == "one"  # warms a's cache
    b.store("two", "postgres postgres postgres")  # written by the other connection
    assert {m["key"] for m in a.search("postgres", 5)[0]} == {"one", "two"}
    a.close()
    b.close()
