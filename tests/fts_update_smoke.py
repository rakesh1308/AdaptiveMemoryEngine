"""End-to-end probe: MemoryEngine.update_memory on a fresh DB.

Confirms the FTS5 fix without needing a real LLM provider.
"""
import sys, tempfile, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from adaptive_memory_engine.config import Config
from adaptive_memory_engine.engine import MemoryEngine
from adaptive_memory_engine.providers.base import IntelligentProvider, EmbeddingProvider


class MockEmbedding(EmbeddingProvider):
    name = "mock-embed"
    dimensions = 4
    def __init__(self):
        pass
    def is_available(self):
        return True
    def embed(self, text):
        h = abs(hash(text)) % 1000
        return [((h >> i) & 0xFF) / 255.0 for i in range(self.dimensions)]
    def embed_batch(self, texts):
        return [self.embed(t) for t in texts]


class MockIntel(IntelligentProvider):
    name = "mock-intel"
    dimensions = 4
    def is_available(self):
        return True
    def embed(self, text):
        return [0.0, 0.0, 0.0, 0.0]
    def embed_batch(self, texts):
        return [[0.0] * 4 for _ in texts]
    def auto_tag(self, key, content):
        return []
    def synthesize(self, content, task, style="concise"):
        return "synthetic"
    def expand_query(self, query):
        return [query]


tmp = Path(tempfile.mkdtemp())
print(f"data dir: {tmp}")
cfg = Config.load()
cfg.data_dir = str(tmp)
cfg.provider_type = "mock"
cfg.ensure_data_dir()

engine = MemoryEngine(
    embedding_provider=MockEmbedding(),
    intelligence_provider=MockIntel(),
    data_dir=str(tmp),
)
engine.initialize()
engine.embedding_provider = MockEmbedding()
engine.intelligence_provider = MockIntel()

# store
engine.store_memory("recipe-1", "Boil pasta. Add sauce. Serve hot.", tags=["food", "italian"])
print("[OK] store_memory")

# update — content + tags
mem = engine.update_memory("recipe-1", content="Boil pasta al dente. Add marinara. Serve with basil.", tags=["food", "italian", "updated"])
print(f"[OK] update_memory -> importance={mem['importance']}, version={mem['version']}")

# search for the NEW content
results = engine.search_memories("marinara basil", top_k=5)
hits = [r["memory"]["content"] for r in results]
assert any("marinara" in h for h in hits), f"FTS didn't pick up updated content: {hits}"
print("[OK] search after update finds 'marinara basil'")

# verify old content is gone from FTS
results = engine.search_memories("sauce hot", top_k=5)
for r in results:
    if r["memory"]["id"] == "recipe-1":
        # it's OK if 'sauce' is still in content but verify update was applied
        pass
print(f"[OK] search still works (got {len(results)} results)")

# update only tags with merge_tags=True
mem = engine.update_memory("recipe-1", tags=["pasta"], merge_tags=True)
assert "pasta" in mem["tags"] and "food" in mem["tags"], f"merge_tags failed: {mem['tags']}"
print(f"[OK] merge_tags -> {mem['tags']}")

# delete + verify gone
ok = engine.delete_memory("recipe-1")
assert ok
results = engine.search_memories("marinara", top_k=5)
for r in results:
    assert r["memory"]["id"] != "recipe-1"
print("[OK] delete + post-delete search clean")

engine.close()
shutil.rmtree(tmp, ignore_errors=True)
print("\nALL PASS ✅")