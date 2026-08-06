"""Memory lifecycle: importance scoring, Ebbinghaus decay, Jaccard consolidation.

These run automatically during `MemoryEngine.store_memory` and on a
background tick. They determine how memory importance and strength evolve
over time and surface consolidation opportunities.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return None


def _days_since(iso: str | None) -> float:
    dt = _parse_iso(iso)
    if not dt:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)


class ImportanceScorer:
    WEIGHTS = {
        "accessFrequency": 0.25,
        "recency": 0.20,
        "userRating": 0.20,
        "graphCentrality": 0.15,
        "contentQuality": 0.10,
        "referenceCount": 0.10,
    }

    def __init__(self, weights: dict | None = None) -> None:
        if weights:
            self.WEIGHTS.update(weights)

    def calculate(self, memory: dict, graph_node: dict | None = None) -> int:
        access_count = int(memory.get("accessCount", 0))
        freq_score = min(1.0, math.log1p(access_count) / math.log1p(20))
        days = _days_since(memory.get("updatedAt") or memory.get("createdAt"))
        recency_score = math.exp(-days / (30 * 86400.0))
        importance_hint = int(memory.get("importance", 50)) / 100.0
        centrality = float((graph_node or {}).get("centrality", 0))
        graph_score = min(1.0, centrality)
        content_score = self.assess_content_quality(memory.get("content", ""))
        ref_score = min(1.0, len((graph_node or {}).get("memoryIds", [])) / 20.0)

        score = (
            self.WEIGHTS["accessFrequency"] * freq_score
            + self.WEIGHTS["recency"] * recency_score
            + self.WEIGHTS["userRating"] * importance_hint
            + self.WEIGHTS["graphCentrality"] * graph_score
            + self.WEIGHTS["contentQuality"] * content_score
            + self.WEIGHTS["referenceCount"] * ref_score
        )
        return max(0, min(100, round(score * 100)))

    @staticmethod
    def assess_content_quality(content: str) -> float:
        if not content:
            return 0.0
        score = 0.5
        length = len(content)
        if 500 < length < 10_000:
            score += 0.2
        elif length >= 10_000:
            score += 0.1
        if re.search(r"^#{1,6}\s", content, re.MULTILINE):
            score += 0.1
        if "```" in content:
            score += 0.1
        if re.search(r"\bhttps?://", content):
            score += 0.1
        words = content.split()
        unique = set(w.lower() for w in words)
        if words and len(unique) / len(words) > 0.5:
            score += 0.1
        return min(1.0, score)


class DecayEngine:
    """Ebbinghaus-style retention: retention = exp(-days / stability)
    where stability = halfLife * (1 + importance / 50)."""

    def __init__(self, half_life_days: float = 30.0) -> None:
        self.half_life_days = half_life_days

    def compute_strength(self, memory: dict) -> float:
        days = _days_since(memory.get("updatedAt") or memory.get("createdAt"))
        importance = int(memory.get("importance", 50))
        stability = self.half_life_days * (1 + importance / 50.0)
        if stability <= 0:
            return 1.0
        return math.exp(-days / stability)

    def should_review(self, memory: dict) -> dict:
        strength = self.compute_strength(memory)
        if strength < 0.3:
            return {"needed": True, "priority": "high", "strength": strength}
        if strength < 0.5:
            return {"needed": True, "priority": "medium", "strength": strength}
        if strength < 0.7:
            return {"needed": True, "priority": "low", "strength": strength}
        return {"needed": False, "strength": strength}

    def apply_decay(self, memories: Iterable[dict]) -> list[dict]:
        out = []
        for m in memories:
            m["strength"] = round(self.compute_strength(m), 4)
            out.append(m)
        return out


class ConsolidationEngine:
    DEFAULT_THRESHOLD = 0.85

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold

    @staticmethod
    def _jaccard(a: str, b: str) -> float:
        wa, wb = set(a.lower().split()), set(b.lower().split())
        if not wa or not wb:
            return 0.0
        inter = wa & wb
        union = wa | wb
        return len(inter) / len(union)

    def calculate_similarity(self, a: dict, b: dict) -> float:
        content_sim = self._jaccard(a.get("content", ""), b.get("content", ""))
        ta, tb = set(a.get("tags") or []), set(b.get("tags") or [])
        tag_bonus = 0.0
        if ta and tb:
            tag_bonus = 0.2 * (len(ta & tb) / max(1, len(ta | tb)))
        return min(1.0, content_sim + tag_bonus)

    def find_duplicates(self, memories: list[dict]) -> list[list[dict]]:
        groups: list[list[dict]] = []
        parent: dict[int, int] = {}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        for i in range(len(memories)):
            parent[i] = i
        for i in range(len(memories)):
            for j in range(i + 1, len(memories)):
                if self.calculate_similarity(memories[i], memories[j]) >= self.threshold:
                    union(i, j)
        buckets: dict[int, list[dict]] = {}
        for i, m in enumerate(memories):
            buckets.setdefault(find(i), []).append(m)
        for grp in buckets.values():
            if len(grp) > 1:
                groups.append(grp)
        return groups

    def merge_memories(self, group: list[dict]) -> dict:
        primary = max(group, key=lambda m: int(m.get("accessCount", 0)) + int(m.get("importance", 0)))
        merged_tags: set[str] = set(primary.get("tags") or [])
        total_access = sum(int(m.get("accessCount", 0)) for m in group)
        for m in group:
            for t in (m.get("tags") or []):
                merged_tags.add(t)
        # Pick the longest content as combined content (Node behaviour)
        combined = max(group, key=lambda m: len(m.get("content", ""))).get("content", "")
        return {
            **primary,
            "tags": sorted(merged_tags),
            "accessCount": total_access,
            "content": combined,
            "mergedFrom": [m["id"] for m in group if m["id"] != primary["id"]],
        }


class MemoryLifecycle:
    """Orchestrator. Drops the timers and ArchiveManager (kept in Node only as in-memory state)."""

    def __init__(self, event_bus=None) -> None:
        self.event_bus = event_bus
        self.importance_scorer = ImportanceScorer()
        self.decay_engine = DecayEngine()
        self.consolidation_engine = ConsolidationEngine()

    def record_access(self, memory: dict, context: dict | None = None) -> dict:
        memory["accessCount"] = int(memory.get("accessCount", 0)) + 1
        memory["strength"] = min(1.0, float(memory.get("strength", 1.0)) + 0.1)
        if self.event_bus:
            self.event_bus.publish("memory:accessed", {"id": memory.get("id"), "context": context})
        return memory

    def update_memory(self, memory: dict, graph_node: dict | None = None) -> dict:
        memory["importance"] = self.importance_scorer.calculate(memory, graph_node)
        memory["strength"] = round(self.decay_engine.compute_strength(memory), 4)
        if self.event_bus:
            self.event_bus.publish("importance:updated", {"id": memory.get("id"), "importance": memory["importance"]})
        return memory

    def run_consolidation(self, memories: list[dict]) -> list[dict]:
        groups = self.consolidation_engine.find_duplicates(memories)
        merged = [self.consolidation_engine.merge_memories(g) for g in groups]
        if self.event_bus:
            self.event_bus.publish("consolidation:run", {"groupsFound": len(groups)})
        return merged