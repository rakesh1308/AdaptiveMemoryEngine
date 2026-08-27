"""Knowledge graph — concept + relationship store.

Concepts: dict of normalized_id -> {id, name, frequency, memoryIds, relatedConcepts, centrality, createdAt}
Relationships: list of {id, from, to, type, strength, evidence, createdAt}
Persisted to `data/knowledge-graph.json`.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import defaultdict
from functools import wraps
from pathlib import Path
from typing import Any

from .events import now_iso

log = logging.getLogger(__name__)


def _graph_locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


VALID_RELATIONSHIPS = {
    "related_to",
    "co_occurs_with",
    "tagged_as",
    "prerequisite_for",
    "implements",
    "part_of",
    "uses",
    "built_with",
}

# Bound pairwise graph expansion. Twenty concepts still permit 190 evidence
# edges per memory while preventing pathological O(n²) graph files.
MAX_CONCEPTS_PER_MEMORY = 20


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
        self._relationship_by_id: dict[str, dict] = {}
        self.concept_index: dict[str, set[str]] = defaultdict(set)
        self._dirty = False
        self._lock = threading.RLock()
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
            # relatedConcepts may be stored either as a dict (Python side)
            # or as a list of [other, strength] pairs (Node JSON). Normalize
            # to a dict here so add_relationship() never crashes calling
            # .get() on a list. Save() will re-emit the list-of-pairs shape
            # for Node compatibility.
            rc = node.get("relatedConcepts") if isinstance(node, dict) else None
            if isinstance(rc, list):
                normalized: dict[str, float] = {}
                for entry in rc:
                    if isinstance(entry, (list, tuple)) and len(entry) == 2:
                        other, weight = entry[0], entry[1]
                        if isinstance(other, str) and other:
                            try:
                                normalized[other] = float(weight)
                            except (TypeError, ValueError):
                                normalized[other] = 0.0
                    elif isinstance(entry, dict):
                        other = entry.get("concept") or entry.get("id")
                        weight = entry.get("strength", 0)
                        if isinstance(other, str) and other:
                            try:
                                normalized[other] = float(weight)
                            except (TypeError, ValueError):
                                normalized[other] = 0.0
                node["relatedConcepts"] = normalized
            elif not isinstance(rc, dict):
                node["relatedConcepts"] = {}
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
        self._relationship_by_id = {
            relationship["id"]: relationship
            for relationship in rels
            if isinstance(relationship, dict) and relationship.get("id")
        }
        for cid, mem_ids in data.get("conceptIndex", []):
            # Defensive: drop anything that isn't a string. Older builds (or a
            # corrupted file) could have written `null` here, which then makes
            # sorted() crash with `'<' not supported between 'NoneType' and 'str'`.
            self.concept_index[cid] = {m for m in mem_ids if isinstance(m, str)}

    def save(self) -> None:
        with self._lock:
            # Defensive: coerce every memory id to str before sorting, and
            # silently drop None/empty entries. This both fixes autosave
            # crashes from older builds and self-heals the on-disk file.
            cleaned: list[list] = []
            for cid, ids in self.concept_index.items():
                valid = [i for i in ids if isinstance(i, str) and i]
                if valid:
                    cleaned.append([cid, sorted(valid)])
            # Serialise relatedConcepts as a list of [other, strength] pairs to
            # match the Node on-disk shape and keep _load() idempotent. Defensive
            # against non-dict values (corrupt file, older Python build).
            concepts_payload: list[list] = []
            for cid, node in self.concepts.items():
                if not isinstance(node, dict):
                    concepts_payload.append([cid, node])
                    continue
                rc = node.get("relatedConcepts")
                if isinstance(rc, dict):
                    serialised_rc = [[k, float(v)] for k, v in rc.items() if isinstance(k, str)]
                elif isinstance(rc, list):
                    serialised_rc = rc  # already in Node shape, pass through
                else:
                    serialised_rc = []
                node_copy = dict(node)
                node_copy["relatedConcepts"] = serialised_rc
                concepts_payload.append([cid, node_copy])
            payload = {
                "concepts": concepts_payload,
                "relationships": self.relationships,
                "conceptIndex": cleaned,
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

    @_graph_locked
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

    @_graph_locked
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
        existing = self._relationship_by_id.get(rid)
        if existing:
            if memory_id and memory_id not in existing["evidence"]:
                existing["evidence"].append(memory_id)
            existing["strength"] = min(1.0, max(existing.get("strength", 0), strength))
        else:
            relationship = {
                "id": rid,
                "from": a,
                "to": b,
                "type": rel_type,
                "strength": strength,
                "evidence": [memory_id] if memory_id else [],
                "createdAt": now_iso(),
            }
            self.relationships.append(relationship)
            self._relationship_by_id[rid] = relationship
        # Update relatedConcepts map
        for nid in (a, b):
            node = self.concepts.get(nid)
            if node:
                rels = node.setdefault("relatedConcepts", {})
                other = b if nid == a else a
                rels[other] = max(rels.get(other, 0), strength)
        self.mark_dirty()
        if self.event_bus:
            self.event_bus.publish(
                "relationship:added", {"id": rid, "from": a, "to": b, "type": rel_type}
            )

    # ---- queries ----

    @_graph_locked
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

    @_graph_locked
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

    @_graph_locked
    def get_stats(self) -> dict[str, Any]:
        if not self.concepts:
            return {"concepts": 0, "relationships": 0, "top": []}
        top = sorted(self.concepts.values(), key=lambda n: n.get("frequency", 0), reverse=True)[:10]
        return {
            "concepts": len(self.concepts),
            "relationships": len(self.relationships),
            "top": [
                {"id": n["id"], "name": n["name"], "frequency": n.get("frequency", 0)} for n in top
            ],
        }

    # ---- intelligence-assisted build ----

    @_graph_locked
    def build_from_memory(
        self, memory_id: str, content: str, tags: list[str], intelligence=None
    ) -> None:
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
            if len(seen) >= MAX_CONCEPTS_PER_MEMORY:
                break

        # Pairwise co-occurrence relationships
        ids = list(seen)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                self.add_relationship(ids[i], ids[j], "co_occurs_with", memory_id, strength=0.4)

    @_graph_locked
    def delete_memory(self, memory_id: str) -> None:
        """Remove a memory and rebuild derived graph links."""
        for cid in list(self.concept_index.keys()):
            if memory_id in self.concept_index[cid]:
                self.concept_index[cid].discard(memory_id)
            if not self.concept_index[cid]:
                del self.concept_index[cid]
        for node in self.concepts.values():
            ids = node.get("memoryIds", [])
            if memory_id in ids:
                node["memoryIds"] = [i for i in ids if i != memory_id]
                node["frequency"] = max(0, int(node.get("frequency", 0)) - 1)
        # Remove evidence
        for r in self.relationships:
            r["evidence"] = [e for e in r.get("evidence", []) if e != memory_id]
        self.relationships = [r for r in self.relationships if r.get("evidence")]
        self._relationship_by_id = {r["id"]: r for r in self.relationships}
        # Remove concepts no longer backed by any memory, then rebuild the
        # denormalized adjacency map from surviving relationships.
        self.concepts = {cid: node for cid, node in self.concepts.items() if node.get("memoryIds")}
        for node in self.concepts.values():
            node["relatedConcepts"] = {}
        for relationship in self.relationships:
            a, b = relationship["from"], relationship["to"]
            strength = float(relationship.get("strength", 0.0))
            if a in self.concepts and b in self.concepts:
                self.concepts[a]["relatedConcepts"][b] = strength
                self.concepts[b]["relatedConcepts"][a] = strength
        self.mark_dirty()
