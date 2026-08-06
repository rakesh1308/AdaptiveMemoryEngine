"""Provider base classes.

`EmbeddingProvider` is the minimal contract (embed a string into a
vector + check availability). `IntelligentProvider` adds LLM-backed
helpers used by the RAG layer (auto-tag, synthesize, expand-query).
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Iterable


class EmbeddingProvider(ABC):
    """Required methods. Mirrors Node `EmbeddingProvider` interface."""

    name: str = "base"
    dimensions: int = 1536

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: Iterable[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def similarity(self, a: list[float], b: list[float]) -> float:
        return _cosine(a, b)

    def get_config(self) -> dict:
        return {"type": self.name, "dimensions": self.dimensions}


class IntelligentProvider(EmbeddingProvider):
    """Adds LLM-backed helpers (autoTag, synthesize, expandQuery)."""

    @abstractmethod
    def auto_tag(self, key: str, content: str) -> list[str]: ...

    @abstractmethod
    def synthesize(self, content: str, task: str, style: str = "concise") -> str: ...

    @abstractmethod
    def expand_query(self, query: str) -> list[str]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)