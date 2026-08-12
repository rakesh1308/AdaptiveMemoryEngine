"""MemoryEngine — top-level orchestrator that wires storage, embeddings,
the knowledge graph, chunking, and the lifecycle layer together."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from .chunking import ChunkStore
from .events import EventBus, MemoryEvents, now_iso
from .knowledge_graph import KnowledgeGraph
from .lifecycle import MemoryLifecycle
from .providers.base import IntelligentProvider
from .storage import SQLiteBackend, VectorStore

log = logging.getLogger(__name__)


class MemoryEngine:
    def __init__(
        self,
        embedding_provider,
        intelligence_provider: IntelligentProvider | None = None,
        data_dir: str | Path = "./data",
        event_bus: EventBus | None = None,
    ) -> None:
        if embedding_provider is None:
            raise ValueError("embedding_provider is required")
        if not embedding_provider.is_available():
            raise ValueError("embedding_provider is not available — check API key/connectivity")

        self.embedding_provider = embedding_provider
        self.intelligence_provider = intelligence_provider
        self.data_dir = Path(data_dir)
        self.event_bus = event_bus or EventBus()

        self.sqlite = SQLiteBackend(self.data_dir)
        self.vector_store = VectorStore(self.embedding_provider)
        self.chunk_store = ChunkStore(event_bus=self.event_bus)
        self.knowledge_graph = KnowledgeGraph(self.data_dir, event_bus=self.event_bus)
        self.lifecycle = MemoryLifecycle(event_bus=self.event_bus)

        # In-memory cache mirrors Node's `this.memories = new Map()`
        self._memories: dict[str, dict] = {}
        self._initialized = False
        self._lock = threading.Lock()

    # ---- lifecycle ----

    def initialize(self) -> None:
        if self._initialized:
            return
        log.info("Initializing engine in %s", self.data_dir)
        self.sqlite.initialize()
        # Load all memories into the in-memory cache
        for m in self.sqlite.get_all():
            self._memories[m["id"]] = m
        # Load embeddings into VectorStore (legacy: id == memoryId)
        for memory_id, vector in self.sqlite.get_all_embeddings().items():
            self.vector_store.add(memory_id, vector, metadata={"memoryId": memory_id})
        # Start autosave thread for knowledge graph
        self._start_graph_autosave()
        self._initialized = True
        log.info("Loaded %d memories", len(self._memories))

    def _start_graph_autosave(self) -> None:
        stop = threading.Event()

        def _loop() -> None:
            while not stop.wait(self.knowledge_graph.AUTOSAVE_SECONDS):
                try:
                    self.knowledge_graph.autosave_tick()
                except Exception:  # noqa: BLE001
                    log.exception("Graph autosave failed")

        t = threading.Thread(target=_loop, name="graph-autosave", daemon=True)
        t.start()
        self._graph_autosave_stop = stop

    def close(self) -> None:
        if not self._initialized:
            return
        self.knowledge_graph.save()
        self.sqlite.close()
        self._initialized = False

    # ---- memory CRUD ----

    def store_memory(
        self,
        key: str,
        content: str,
        tags: list[str] | None = None,
        auto_tag: bool = False,
        source: str = "user",
    ) -> dict:
        tags = tags or []
        if auto_tag and self.intelligence_provider:
            try:
                ai_tags = self.intelligence_provider.auto_tag(key, content)
                tags = sorted(set(tags) | set(ai_tags))
            except Exception:  # noqa: BLE001
                log.warning("auto_tag failed for %s", key)

        now = now_iso()
        existing = self.sqlite.get(key)
        mem = {
            "id": key,
            "content": content,
            "tags": tags,
            "createdAt": existing["createdAt"] if existing else now,
            "updatedAt": now,
            "importance": existing["importance"] if existing else 50,
            "strength": existing["strength"] if existing else 1.0,
            "accessCount": existing["accessCount"] if existing else 0,
            "source": source,
            "version": int(existing["version"]) + 1 if existing else 1,
        }
        mem["importance"] = self.lifecycle.importance_scorer.calculate(mem)
        self.sqlite.insert(mem)
        self._memories[key] = mem

        # Chunk + embed (mirrors Node: chunk then embed each)
        chunks = self.chunk_store.chunk_content(content)
        if chunks:
            try:
                texts = [c["content"] for c in chunks]
                embeddings = self.embedding_provider.embed_batch(texts)
                self.chunk_store.store_chunks(key, chunks, embeddings)
                # Save last chunk vector to SQLite (matches Node's last-chunk-wins)
                self.sqlite.save_embedding(key, embeddings[-1])
                # Add per-chunk vectors to VectorStore
                for i, emb in enumerate(embeddings):
                    self.vector_store.add(f"{key}__{i}", emb, metadata={"memoryId": key, "chunkIndex": i})
            except Exception:  # noqa: BLE001
                log.exception("Embedding failed for %s", key)
                # Fallback: embed whole content as single vector
                try:
                    vec = self.embedding_provider.embed(content)
                    self.sqlite.save_embedding(key, vec)
                    self.vector_store.add(key, vec, metadata={"memoryId": key})
                except Exception:  # noqa: BLE001
                    log.exception("Whole-content embedding also failed for %s", key)

        # Update knowledge graph
        try:
            self.knowledge_graph.build_from_memory(
                key, content, tags, intelligence=self.intelligence_provider
            )
        except Exception:  # noqa: BLE001
            log.exception("Graph update failed for %s", key)

        self.event_bus.publish(MemoryEvents.MEMORY_CREATED, mem)
        return mem

    def recall_memory(self, key: str) -> dict | None:
        mem = self._memories.get(key)
        if not mem:
            mem = self.sqlite.get(key)
        if not mem:
            return None
        self.lifecycle.record_access(mem)
        try:
            self.sqlite.record_access(key, {})
        except Exception:  # noqa: BLE001
            log.warning("access_log write failed for %s", key)
        # Update in-memory + persist new strength
        mem["strength"] = min(1.0, mem.get("strength", 1.0))
        self._memories[key] = mem
        self.sqlite.update(key, {"strength": mem["strength"], "accessCount": mem["accessCount"]})
        return mem

    def update_memory(
        self,
        key: str,
        content: str | None = None,
        tags: list[str] | None = None,
        merge_tags: bool = False,
    ) -> dict | None:
        existing = self.sqlite.get(key)
        if not existing:
            return None
        new_content = content if content is not None else existing["content"]
        new_tags: list[str]
        if tags is None:
            new_tags = existing.get("tags", [])
        elif merge_tags:
            new_tags = sorted(set(existing.get("tags", [])) | set(tags))
        else:
            new_tags = tags
        return self.store_memory(key, new_content, new_tags, auto_tag=False, source=existing.get("source", "user"))

    def delete_memory(self, key: str) -> bool:
        if not self.sqlite.get(key):
            return False
        self.sqlite.delete(key)
        self.chunk_store.delete_memory_chunks(key)
        self._memories.pop(key, None)
        # Remove vectors
        for vid in [k for k in list(self.vector_store.vectors.keys()) if k == key or k.startswith(f"{key}__")]:
            self.vector_store.remove(vid)
        self.knowledge_graph.delete_memory(key)
        self.event_bus.publish(MemoryEvents.MEMORY_DELETED, {"id": key})
        return True

    # ---- search ----

    def search_memories(
        self,
        query: str,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> list[dict]:
        """Returns list of memories sorted by relevance (with 'score' field)."""
        # Keyword (FTS) stage
        keyword_hits = self.sqlite.search_keyword(query, limit=50)
        keyword_ids = [m["id"] for m in keyword_hits]

        if mode == "keyword" or not self._memories:
            return [{"memory": m, "score": 1.0 - i / max(len(keyword_hits), 1)}
                    for i, m in enumerate(keyword_hits[:top_k])]

        # Semantic stage
        try:
            query_vec = self.embedding_provider.embed(query)
        except Exception:  # noqa: BLE001
            log.exception("Query embedding failed")
            return [{"memory": m, "score": 1.0 - i / max(len(keyword_hits), 1)}
                    for i, m in enumerate(keyword_hits[:top_k])]

        if mode == "semantic":
            scored = []
            for entry, score in self.vector_store.search(query_vec, top_k=top_k):
                mem_id = entry.metadata.get("memoryId", entry.id)
                mem = self._memories.get(mem_id) or self.sqlite.get(mem_id)
                if mem:
                    scored.append({"memory": mem, "score": score})
            # de-dup by memory id, keep best
            seen: dict[str, dict] = {}
            for r in scored:
                mid = r["memory"]["id"]
                if mid not in seen or r["score"] > seen[mid]["score"]:
                    seen[mid] = r
            return sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:top_k]

        # hybrid (default)
        ranked = self.vector_store.hybrid_search(query, query_vec, keyword_ids, top_k=top_k)
        out: list[dict] = []
        for entry, score in ranked:
            mem_id = entry.metadata.get("memoryId", entry.id)
            mem = self._memories.get(mem_id) or self.sqlite.get(mem_id)
            if mem:
                out.append({"memory": mem, "score": score})
        # Boost pure keyword hits not seen by semantic
        seen_ids = {r["memory"]["id"] for r in out}
        for i, m in enumerate(keyword_hits):
            if m["id"] not in seen_ids:
                out.append({"memory": m, "score": 0.5 * (1.0 - i / max(len(keyword_hits), 1))})
        return sorted(out, key=lambda x: x["score"], reverse=True)[:top_k]

    def list_memories(
        self,
        filter_text: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        sort_by: str = "createdAt",
    ) -> list[dict]:
        if tag:
            items = self.sqlite.get_by_tag(tag)
        else:
            items = list(self._memories.values()) or self.sqlite.get_all()
        if filter_text:
            ft = filter_text.lower()
            items = [m for m in items if ft in m.get("content", "").lower() or ft in m.get("id", "").lower()]
        # Sort
        if sort_by == "createdAt":
            items.sort(key=lambda m: m.get("createdAt") or "", reverse=True)
        elif sort_by == "updatedAt":
            items.sort(key=lambda m: m.get("updatedAt") or "", reverse=True)
        elif sort_by == "importance":
            items.sort(key=lambda m: m.get("importance", 0), reverse=True)
        return items[:limit]

    # ---- graph ----

    def query_graph(
        self,
        concept: str | None = None,
        depth: int = 1,
        find_path_to: str | None = None,
    ) -> dict:
        if find_path_to:
            path = self.knowledge_graph.find_path(concept or "", find_path_to)
            return {"from": concept, "to": find_path_to, "path": path}
        if concept:
            return self.knowledge_graph.get_related_concepts(concept, depth)
        return self.knowledge_graph.get_stats()

    # ---- AI features ----

    def ask(self, question: str, context_limit: int = 3) -> str:
        results = self.search_memories(question, top_k=context_limit, mode="hybrid")
        context = "\n\n---\n\n".join(
            f"[{r['memory'].get('id')}] {r['memory'].get('content', '')[:1500]}"
            for r in results
        )
        if not self.intelligence_provider:
            return self._ask_fallback(question, results)
        try:
            return self.intelligence_provider.synthesize(
                context,
                f"Answer the question using the provided memory context.\n\nQuestion: {question}",
                style="detailed",
            )
        except Exception as e:  # noqa: BLE001
            log.exception("ask failed")
            return self._ask_fallback(question, results) + f"\n\n[AI error: {e}]"

    def _ask_fallback(self, question: str, results: list[dict]) -> str:
        if not results:
            return f"No memories found for: {question}"
        lines = [f"Top {len(results)} memories for '{question}':", ""]
        for i, r in enumerate(results, 1):
            m = r["memory"]
            lines.append(f"{i}. [{m['id']}] (score: {r['score']:.3f})")
            lines.append(f"   {m.get('content', '')[:400]}")
            lines.append("")
        return "\n".join(lines)

    def summarize(self, query: str | None = None, keys: list[str] | None = None, style: str = "concise") -> str:
        if keys:
            memories = [self.recall_memory(k) for k in keys]
            memories = [m for m in memories if m]
            heading = f"Summary of {len(memories)} memories"
        elif query:
            memories = [r["memory"] for r in self.search_memories(query, top_k=5, mode="hybrid")]
            heading = f"Summary of memories matching '{query}'"
        else:
            memories = self.list_memories(limit=20)
            heading = "Summary of recent memories"
        if not memories:
            return "No memories to summarize."
        if not self.intelligence_provider:
            return self._summarize_fallback(heading, memories, style)
        content = "\n\n---\n\n".join(
            f"[{m['id']}] {m.get('content', '')[:1500]}" for m in memories
        )
        try:
            return self.intelligence_provider.synthesize(content, heading, style=style)
        except Exception as e:  # noqa: BLE001
            log.exception("summarize failed")
            return self._summarize_fallback(heading, memories, style) + f"\n\n[AI error: {e}]"

    @staticmethod
    def _summarize_fallback(heading: str, memories: list[dict], style: str) -> str:
        lines = [heading, ""]
        for i, m in enumerate(memories, 1):
            content = m.get("content", "")
            if style == "concise":
                snippet = content[:120].replace("\n", " ")
            else:
                snippet = content[:400].replace("\n", " ")
            lines.append(f"{i}. [{m['id']}] {snippet}{'...' if len(content) > len(snippet) else ''}")
        return "\n".join(lines)

    # ---- stats / export / backup ----

    def get_stats(self) -> dict:
        s = self.sqlite.get_stats()
        return {
            **s,
            "concepts": len(self.knowledge_graph.concepts),
            "relationships": len(self.knowledge_graph.relationships),
            "embeddingProvider": self.embedding_provider.get_config(),
            "intelligenceProvider": (
                self.intelligence_provider.get_config() if self.intelligence_provider else None
            ),
        }

    def export(self) -> dict:
        return {
            "exportedAt": now_iso(),
            "memories": self.list_memories(limit=10_000),
            "graph": {
                "concepts": list(self.knowledge_graph.concepts.values()),
                "relationships": self.knowledge_graph.relationships,
            },
        }

    def create_snapshot(self) -> dict:
        self.knowledge_graph.save()
        snapshots_dir = self.data_dir / "snapshots"
        snapshots_dir.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = snapshots_dir / f"snapshot-{ts}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.export(), f, ensure_ascii=False, indent=2)
        self.event_bus.publish(MemoryEvents.BACKUP_CREATED, {"path": str(path)})
        return {"path": str(path), "size": path.stat().st_size}

    # ---- graph maintenance ----

    def backfill_graph(
        self,
        memory_ids: list[str] | None = None,
        dry_run: bool = False,
        rebuild_all: bool = False,
    ) -> dict:
        """Ensure every memory is represented in the knowledge graph.

        By default, only memories that are missing from `concept_index` are
        re-run through `build_from_memory`. With `rebuild_all=True`, every
        supplied memory is re-extracted (useful when changing extractors).

        Args:
            memory_ids: restrict to these keys. If None, scans all memories.
            dry_run: report what would change without mutating the graph.
            rebuild_all: re-run extraction even for already-indexed memories.
        """
        all_memories = self.sqlite.get_all()
        if memory_ids is not None:
            wanted = set(memory_ids)
            all_memories = [m for m in all_memories if m["id"] in wanted]

        # Memories that have at least one concept linked are "indexed".
        already_indexed: set[str] = set()
        for ids in self.knowledge_graph.concept_index.values():
            for mid in ids:
                if isinstance(mid, str) and mid:
                    already_indexed.add(mid)

        scanned = len(all_memories)
        skipped_already_indexed = 0
        processed: list[str] = []
        errors: list[dict[str, str]] = []

        for mem in all_memories:
            mid = mem["id"]
            if not rebuild_all and mid in already_indexed:
                skipped_already_indexed += 1
                continue
            if dry_run:
                processed.append(mid)
                continue
            try:
                self.knowledge_graph.build_from_memory(
                    mid,
                    mem.get("content", ""),
                    mem.get("tags", []) or [],
                    intelligence=self.intelligence_provider,
                )
                processed.append(mid)
            except Exception as exc:  # noqa: BLE001
                log.exception("backfill_graph failed for %s", mid)
                errors.append({"id": mid, "error": str(exc)})

        if not dry_run:
            self.knowledge_graph.mark_dirty()
            # Save eagerly so the next autosave tick sees a clean file even
            # if the autosave thread happens to be inside _load() at the time.
            self.knowledge_graph.save()

        return {
            "scanned": scanned,
            "skippedAlreadyIndexed": skipped_already_indexed,
            "processed": len(processed),
            "errors": errors,
            "dryRun": dry_run,
            "rebuildAll": rebuild_all,
        }

    # ---- shutdown helper for graceful HTTP termination ----

    def shutdown(self) -> None:
        self.close()