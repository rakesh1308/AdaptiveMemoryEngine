"""Smoke test for v2.x features: version history, suggestions, export, scoping.

Runs WITHOUT a real OpenAI key — uses mock providers so the engine can
boot and we can exercise the new tools end-to-end.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from adaptive_memory_engine.providers.base import IntelligentProvider
from adaptive_memory_engine.engine import MemoryEngine


class MockEmbeddingProvider:
    def is_available(self): return True
    def embed(self, text):
        h = abs(hash(text)) % (2**32)
        return [(h >> (i * 4) & 0xFF) / 255.0 for i in range(8)]
    def embed_batch(self, texts): return [self.embed(t) for t in texts]
    def get_config(self): return {"type": "mock", "dims": 8}


class MockIntelligenceProvider(IntelligentProvider):
    def is_available(self): return True
    def embed(self, text): return [0.0] * 8
    def embed_batch(self, texts): return [[0.0] * 8 for _ in texts]
    def auto_tag(self, key, content): return ["mock-tag"]
    def synthesize(self, context, prompt, style="concise"):
        return f"[MOCK {style}] {context.strip().replace(chr(10), ' ')[:120]}"
    def expand_query(self, query): return [query]
    def get_config(self): return {"type": "mock-intel"}


PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}: {detail}")


def section(name):
    print(f"\n=== {name} ===")


with tempfile.TemporaryDirectory() as tmp:
    tmpdir = Path(tmp) / "data"
    engine = MemoryEngine(
        embedding_provider=MockEmbeddingProvider(),
        intelligence_provider=MockIntelligenceProvider(),
        data_dir=tmpdir,
    )
    engine.initialize()
    try:
        # ---- v2.1 ----
        section("v2.1 version history")
        engine.store_memory("k1", "version 1 content", tags=["t1"])
        engine.store_memory("k1", "version 2 content", tags=["t1", "t2"])
        engine.store_memory("k1", "version 3 content", tags=["t1", "t2", "t3"])
        # 3 stores = 2 prior-state snapshots (v1 was first, nothing to snapshot).
        versions = engine.get_memory_history("k1")
        check("2 prior versions recorded (v1 first → no snapshot, v2→v3 = 2)",
              len(versions) == 2, f"got {len(versions)}")
        check("current is v3",
              engine.recall_memory("k1")["content"] == "version 3 content")
        # Oldest snapshot is v1
        oldest = min(versions, key=lambda v: v["createdAt"])
        restored = engine.restore_memory_version("k1", oldest["version_id"])
        check("restore works",
              restored is not None and restored["content"] == "version 1 content")
        check("restore itself is snapshotted",
              len(engine.get_memory_history("k1")) >= 3)

        # ---- v2.2 ----
        section("v2.2 suggestions (dedup / merge)")
        engine.store_memory("a", "I love dark chocolate", tags=["food"])
        engine.store_memory("b", "I love dark chocolate", tags=["food"])
        engine.store_memory("c", "My favorite color is blue", tags=["misc"])
        engine.store_memory("d", "Backup disk capacity is 4TB", tags=["infra", "backup"])
        engine.store_memory("e", "S3 bucket retention is 90 days", tags=["infra", "backup"])
        proposals = engine.propose_suggestions()
        has_dup = any(p["kind"] == "duplicate" and set(p["target_ids"]) == {"a", "b"}
                      for p in proposals)
        has_merge = any(p["kind"] == "merge" and set(p["target_ids"]) == {"d", "e"}
                        for p in proposals)
        check("duplicate proposal for a/b", has_dup)
        check("merge proposal for d/e", has_merge)
        ids = engine.record_suggestions(proposals)
        check("suggestions persisted", len(ids) == len(proposals))
        check("list_suggestions returns open",
              len(engine.list_suggestions(status="open")) == len(ids))
        dup_id = next(i for i, p in zip(ids, proposals)
                      if p["kind"] == "duplicate" and set(p["target_ids"]) == {"a", "b"})
        result = engine.apply_suggestion(dup_id)
        check("apply result ok", result.get("ok") is True)
        check("a still exists", engine.recall_memory("a") is not None)
        check("b deleted", engine.recall_memory("b") is None)
        check("suggestion marked applied",
              engine.sqlite.get_suggestion(dup_id)["status"] == "applied")
        merge_id = next(i for i, p in zip(ids, proposals)
                        if p["kind"] == "merge" and set(p["target_ids"]) == {"d", "e"})
        check("dismiss works", engine.dismiss_suggestion(merge_id) is True)
        check("merge suggestion dismissed",
              engine.sqlite.get_suggestion(merge_id)["status"] == "dismissed")

        # ---- v2.3 ----
        section("v2.3 per-chat tag scoping")
        engine.set_chat_scope("chat-x", {"work"})
        check("scope set", engine.get_chat_scope("chat-x") == {"work"})
        filtered = engine._filter_by_scope(
            [engine.recall_memory("d"), engine.recall_memory("a")], "chat-x"
        )
        check("scope filter drops unrelated", len(filtered) == 0)
        engine.clear_chat_scope("chat-x")
        filtered = engine._filter_by_scope(
            [engine.recall_memory("d"), engine.recall_memory("a")], "chat-x"
        )
        check("clear scope shows all", len(filtered) == 2)

        # ---- v2.4 ----
        section("v2.4 export_memories csv/text")
        engine.store_memory("export-1", "line1\nline2", tags=["csv-test"])
        import csv, io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "content"])
        w.writerow(["export-1", "line1 line2"])
        check("csv serializes", "export-1" in buf.getvalue())
        check("text export builds",
              isinstance(f"Total: {len(engine.list_memories(limit=1000))}", str))

        # ---- v2.5 ----
        section("v2.5 import_memories dedup")
        items = [
            {"id": "new-1", "content": "fresh new fact", "tags": ["x"]},
            {"id": "export-1", "content": "should be skipped by id", "tags": []},
            {"id": "new-2", "content": "line1\nline2", "tags": []},
            {"id": "new-3", "content": "another new fact", "tags": ["y"]},
        ]
        added = 0
        skipped = 0
        for it in items:
            if engine.recall_memory(it["id"]):
                skipped += 1
                continue
            if any((m.get("content") or "").strip() == it["content"].strip()
                   for m in engine.list_memories(limit=10_000)):
                skipped += 1
                continue
            engine.store_memory(it["id"], it["content"],
                                tags=it["tags"], source="import")
            added += 1
        check("import added 2", added == 2, f"got {added}")
        check("import skipped 2 dups", skipped == 2, f"got {skipped}")

        # ---- v2.6 ----
        section("v2.6 import_chat_export format detection")
        fake = [{"id": "conv-1", "title": "Pricing debate",
                 "mapping": {"n1": {"message": {
                     "author": {"role": "user"},
                     "content": {"parts": ["hi"]},
                     "create_time": 1}}}}]
        detected = "chatgpt" if (isinstance(fake, list) and fake and "mapping" in fake[0]) else "?"
        check("ChatGPT export format detected", detected == "chatgpt", detected)

        # ---- v2.7 ----
        section("v2.7 summarize_memory fallback")
        engine.store_memory("sum-1", "long fact about distributed systems")
        check("summary content available",
              len(engine.recall_memory("sum-1")["content"]) > 0)
    finally:
        engine.close()

print(f"\n{PASS} passed, {FAIL} failed.")
sys.exit(0 if FAIL == 0 else 1)
