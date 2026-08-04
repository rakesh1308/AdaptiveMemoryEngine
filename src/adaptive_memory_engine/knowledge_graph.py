"""Knowledge graph. Mirrors src/intelligence/KnowledgeGraph.js — same JSON shape.

Concepts: dict of normalized_id -> {id, name, frequency, memoryIds, relatedConcepts, centrality, createdAt}
Relationships: list of {id, from, to, type, strength, evidence, createdAt}
"""
from __future__ import annotations

import json
import logging
import re
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .events import now_iso

log = logging.getLogger(__name__)

VALID_RELATIONSHIPS = {
    "related_to", "co_occurs_with", "tagged_as",
    "prerequisite_for", "implements", "part_of", "uses", "built_with",
}


def normalize_concept(concept: str) -> str:
    """Match Node's normalization: lowercase, non-alphanum → _, trim underscores."""
    s = re.sub(r"[^a-z0-9]+", "_", concept.lower()).strip("_")
    return s


class KnowledgeGraph:
    """Concept + relationship graph. Persisted as a single JSON file."""

    AUTOSAVE_SECONDS = 30

    def __init__(self, data_dir: str | Path, event_bus=None) -> None:
        self.data_dir = Path(data_dir)
        self.event_bus = event_bus
        self.graph_file = self.data_dir / "knowledge-graph.json"
        self.concepts: dict[str, dict] = {}
        self.relationships: list[dict] = []
        self.concept_index: dict[str, set[str]] = defaultdict(set)
        self._dirty = False
        self._lock = threading.Lock()
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        if not self.graph_file.exists():
            return
        try:
            with self.graph_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            log.exception("Failed to load knowledge graph")
            return
        # concepts is stored as array of [id, node] to preserve Maps
        for pair in data.get("concepts", []):
            cid, node = pair[0], pair[1]
            self.concepts[cid] = node
        # relationships may be stored either as direct objects or as [id, node] pairs
        # (legacy Node versions wrote them as direct objects, but newer versions use Map
        # serialization to preserve insertion order). Handle both.
        rels = []
        for r in data.get("relationships", []):
            if isinstance(r, list) and len(r) == 2 and isinstance(r[1], dict):
                # [id, node] form
                rels.append(r[1])
            else:
                # direct object form
                rels.append(r)
        self.relationships = rels
        for cid, mem_ids in data.get("conceptIndex", []):
            self.concept_index[cid] = set(mem_ids)

    def save(self) -> None:
        with self._lock:
            payload = {
                "concepts": [[cid, node] for cid, node in self.concepts.items()],
                "relationships": self.relationships,
                "conceptIndex": [[cid, sorted(ids)] for cid, ids in self.concept_index.items()],
                "savedAt": now_iso(),
            }
            tmp = self.graph_file.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            tmp.replace(self.graph_file)
            self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = True

    def autosave_tick(self) -> None:
        if self._dirty:
            self.save()

    # ---- mutations ----

    def add_concept(self, name: str, memory_id: str | None = None) -> str:
        nid = normalize_concept(name)
        if not nid:
            return ""
        node = self.concepts.get(nid)
        if not node:
            node = {
                "id": nid,
                "name": name,
                "frequency": 0,
                "memoryIds": [],
                "relatedConcepts": {},
                "centrality": 0,
                "createdAt": now_iso(),
            }
            self.concepts[nid] = node
        node["frequency"] = int(node.get("frequency", 0)) + 1
        if memory_id and memory_id not in node["memoryIds"]:
            node["memoryIds"].append(memory_id)
        if memory_id:
            self.concept_index[nid].add(memory_id)
        self.mark_dirty()
        if self.event_bus:
            self.event_bus.publish("concept:extracted", {"id": nid, "name": name})
        return nid

    def add_relationship(
        self,
        from_concept: str,
        to_concept: str,
        rel_type: str = "related_to",
        memory_id: str | None = None,
        strength: float = 0.5,
    ) -> None:
        if rel_type not in VALID_RELATIONSHIPS:
            rel_type = "related_to"
        a = normalize_concept(from_concept)
        b = normalize_concept(to_concept)
        if not a or not b or a == b:
            return
        rid = f"{a}__{rel_type}__{b}"
        # De-duplicate
        existing = next((r for r in self.relationships if r["id"] == rid), None)
        if existing:
            if memory_id and memory_id not in existing["evidence"]:
                existing["evidence"].append(memory_id)
            existing["strength"] = min(1.0, max(existing.get("strength", 0), strength))
        else:
            self.relationships.append({
                "id": rid,
                "from": a,
                "to": b,
                "type": rel_type,
                "strength": strength,
                "evidence": [memory_id] if memory_id else [],
                "createdAt": now_iso(),
            })
        # Update relatedConcepts map
        for nid in (a, b):
            node = self.concepts.get(nid)
            if node:
                rels = node.setdefault("relatedConcepts", {})
                other = b if nid == a else a
                rels[other] = max(rels.get(other, 0), strength)
        self.mark_dirty()
        if self.event_bus:
            self.event_bus.publish("relationship:added", {"id": rid, "from": a, "to": b, "type": rel_type})

    # ---- queries ----

    def get_related_concepts(self, concept: str, depth: int = 1) -> dict[str, Any]:
        start = normalize_concept(concept)
        if not start or start not in self.concepts:
            return {"concept": start, "related": [], "depth": depth}
        visited = {start}
        frontier = {start}
        edges: list[dict] = []
        for _ in range(depth):
            next_frontier: set[str] = set()
            for cid in frontier:
                for r in self.relationships:
                    if r["from"] == cid and r["to"] not in visited:
                        edges.append(r)
                        visited.add(r["to"])
                        next_frontier.add(r["to"])
                    elif r["to"] == cid and r["from"] not in visited:
                        edges.append(r)
                        visited.add(r["from"])
                        next_frontier.add(r["from"])
            frontier = next_frontier
        related = [self.concepts[c] for c in visited if c in self.concepts and c != start]
        return {"concept": start, "related": related, "edges": edges, "depth": depth}

    def find_path(self, from_concept: str, to_concept: str, max_depth: int = 5) -> list[str]:
        a = normalize_concept(from_concept)
        b = normalize_concept(to_concept)
        if a == b:
            return [a]
        # BFS through relationships
        adj: dict[str, set[str]] = defaultdict(set)
        for r in self.relationships:
            adj[r["from"]].add(r["to"])
            adj[r["to"]].add(r["from"])
        if a not in adj and a not in self.concepts:
            return []
        if b not in adj and b not in self.concepts:
            return []
        from collections import deque
        queue: deque[tuple[str, list[str]]] = deque([(a, [a])])
        seen = {a}
        while queue:
            node, path = queue.popleft()
            if node == b:
                return path
            if len(path) > max_depth:
                continue
            for nb in adj.get(node, []):
                if nb not in seen:
                    seen.add(nb)
                    queue.append((nb, path + [nb]))
        return []

    def get_stats(self) -> dict[str, Any]:
        if not self.concepts:
            return {"concepts": 0, "relationships": 0, "top": []}
        top = sorted(self.concepts.values(), key=lambda n: n.get("frequency", 0), reverse=True)[:10]
        return {
            "concepts": len(self.concepts),
            "relationships": len(self.relationships),
            "top": [{"id": n["id"], "name": n["name"], "frequency": n.get("frequency", 0)} for n in top],
        }

    # ---- intelligence-assisted build ----

    def build_from_memory(self, memory_id: str, content: str, tags: list[str], intelligence=None) -> None:
        """Extract concepts from a memory and add to the graph.

        Without an intelligence provider, fall back to regex extraction of capitalized
        phrases and tags. Matches Node behaviour."""
        concepts: list[str] = []

        if intelligence is not None and hasattr(intelligence, "extract_graph_entities"):
            try:
                concepts = list(intelligence.extract_graph_entities(content))
            except Exception:  # noqa: BLE001
                concepts = []

        if not concepts:
            # Heuristic: capitalized bigrams + tags
            for tag in tags or []:
                concepts.append(tag.replace("-", " ").replace("_", " "))
            for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", content):
                concepts.append(m.group(1))

        seen = set()
        for c in concepts:
            norm = normalize_concept(c)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            self.add_concept(c, memory_id)

        # Pairwise co-occurrence relationships
        ids = list(seen)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                self.add_relationship(ids[i], ids[j], "co_occurs_with", memory_id, strength=0.4)

    def delete_memory(self, memory_id: str) -> None:
        """Remove a memory from all concept indexes (concepts remain for stats)."""
        for cid in list(self.concept_index.keys()):
            if memory_id in self.concept_index[cid]:
                self.concept_index[cid].discard(memory_id)
        for node in self.concepts.values():
            ids = node.get("memoryIds", [])
            if memory_id in ids:
                node["memoryIds"] = [i for i in ids if i != memory_id]
        # Remove evidence
        for r in self.relationships:
            r["evidence"] = [e for e in r.get("evidence", []) if e != memory_id]
        self.relationships = [r for r in self.relationships if r.get("evidence")]
        self.mark_dirty()