from __future__ import annotations

import hashlib

import pytest

from adaptive_memory_engine.engine import MemoryEngine
from adaptive_memory_engine.providers.base import IntelligentProvider


class DeterministicProvider(IntelligentProvider):
    name = "test"
    dimensions = 8

    def is_available(self) -> bool:
        return True

    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [byte / 255.0 for byte in digest[: self.dimensions]]

    def auto_tag(self, key: str, content: str) -> list[str]:
        return ["generated"]

    def synthesize(self, content: str, task: str, style: str = "concise") -> str:
        return f"{style}:{task[:20]}:{content[:20]}"

    def expand_query(self, query: str) -> list[str]:
        return [query]


@pytest.fixture
def engine(tmp_path):
    provider = DeterministicProvider()
    instance = MemoryEngine(provider, provider, data_dir=tmp_path)
    instance.initialize()
    yield instance
    instance.close()
