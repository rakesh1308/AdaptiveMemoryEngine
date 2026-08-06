"""Memory lifecycle: importance scoring + access tracking.

Two things actually run during `MemoryEngine` operations:

1. `ImportanceScorer.calculate` — called on every `store_memory` to set
   the `importance` field (0–100) from access frequency, recency,
   graph centrality, content quality, and reference count.
2. `MemoryLifecycle.record_access` — called on every `recall_memory`
   to bump `accessCount` and nudge `strength` upward.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone


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


class MemoryLifecycle:
    """Orchestrator used by MemoryEngine. Tracks access + importance."""

    def __init__(self, event_bus=None) -> None:
        self.event_bus = event_bus
        self.importance_scorer = ImportanceScorer()

    def record_access(self, memory: dict, context: dict | None = None) -> dict:
        memory["accessCount"] = int(memory.get("accessCount", 0)) + 1
        memory["strength"] = min(1.0, float(memory.get("strength", 1.0)) + 0.1)
        if self.event_bus:
            self.event_bus.publish("memory:accessed", {"id": memory.get("id"), "context": context})
        return memory
