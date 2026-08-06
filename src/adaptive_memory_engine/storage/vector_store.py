"""In-memory cosine vector store. Mirrors src/storage/VectorStore.js.

Key format: `${memoryId}__${chunkIndex}` — same as Node.
Holds both whole-memory vectors and per-chunk vectors during a session.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, field

from ..events import now_iso


@dataclass
class VectorEntry:
    id: str
    vector: list[float]
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)


class VectorStore:
    """Linear-scan cosine similarity search. Sufficient for personal-scale memory."""

    _CACHE_MAX = 10_000

    def __init__(self, embedding_provider) -> None:
        self.embedding_provider = embedding_provider
        self.vectors: dict[str, VectorEntry] = {}
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self.dimensions: int = getattr(embedding_provider, "dimensions", 1536)

    # ---- lifecycle ----

    def clear(self) -> None:
        self.vectors.clear()
        self._cache.clear()

    def add(self, entry_id: str, vector: list[float], metadata: dict | None = None) -> None:
        self.vectors[entry_id] = VectorEntry(
            id=entry_id, vector=vector, metadata=metadata or {}
        )

    def remove(self, entry_id: str) -> None:
        self.vectors.pop(entry_id, None)

    def get(self, entry_id: str) -> VectorEntry | None:
        return self.vectors.get(entry_id)

    # ---- search ----

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[tuple[VectorEntry, float]]:
        scored = [
            (entry, self._cosine(query_vector, entry.vector))
            for entry in self.vectors.values()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(e, s) for e, s in scored[:top_k] if s >= min_score]

    def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        keyword_results: list[str],
        top_k: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[tuple[VectorEntry, float]]:
        # Index keyword results
        keyword_score: dict[str, float] = {}
        n = max(len(keyword_results), 1)
        for i, entry_id in enumerate(keyword_results):
            keyword_score[entry_id] = 1.0 - (i / n)

        scored: dict[str, float] = {}
        for entry in self.vectors.values():
            cos = self._cosine(query_vector, entry.vector)
            kw = keyword_score.get(entry.id, 0.0)
            final = semantic_weight * cos + keyword_weight * kw
            scored[entry.id] = final

        ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)[:top_k]
        out: list[tuple[VectorEntry, float]] = []
        for entry_id, score in ranked:
            entry = self.vectors.get(entry_id)
            if entry:
                out.append((entry, score))
        return out

    # ---- helpers ----

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    @staticmethod
    def hash_text(text: str) -> str:
        # Match Node's 32-bit rolling hash output as a hex string
        h = 0
        for ch in text:
            h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
        return f"{h:08x}"

    def cached_embed(self, text: str) -> list[float]:
        key = self.hash_text(text)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        vec = self.embedding_provider.embed(text)
        self._cache[key] = vec
        if len(self._cache) > self._CACHE_MAX:
            self._cache.popitem(last=False)
        return vec