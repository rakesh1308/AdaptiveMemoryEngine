"""Chunking strategies + ChunkStore.

Splits long memory content into smaller windows before embedding so that
similarity search is bounded by chunk size instead of document size.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterable

from .events import now_iso


class ChunkingStrategies:
    """Static chunking strategies. Same names + defaults as the Node version."""

    DEFAULT_CHUNK_SIZE = 2500
    DEFAULT_OVERLAP = 250

    @staticmethod
    def fixed(content: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[dict]:
        chunks: list[dict] = []
        start = 0
        idx = 0
        while start < len(content):
            end = min(start + chunk_size, len(content))
            chunks.append({"index": idx, "content": content[start:end], "start": start, "end": end})
            if end == len(content):
                break
            start = end - overlap
            idx += 1
        return chunks

    @staticmethod
    def paragraph(content: str, max_chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[dict]:
        paragraphs = re.split(r"\n\s*\n", content)
        chunks: list[dict] = []
        current = ""
        idx = 0
        for p in paragraphs:
            if (current + p) and len(current + p) > max_chunk_size and current:
                chunks.append({"index": idx, "content": current.strip(), "start": 0, "end": 0})
                idx += 1
                current = p
            else:
                current = current + ("\n\n" if current else "") + p
        if current.strip():
            chunks.append({"index": idx, "content": current.strip(), "start": 0, "end": 0})
        return chunks

    @staticmethod
    def semantic(content: str, max_chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[dict]:
        """Split on markdown headings / code fences, then sub-chunk oversized sections."""
        # Split keeping the delimiter at the start of each chunk
        parts = re.split(r"(?=^#{1,6}\s|^```|^\n#{1,6}\s)", content, flags=re.MULTILINE)
        parts = [p for p in parts if p.strip()]
        out: list[dict] = []
        idx = 0
        for part in parts:
            if len(part) <= max_chunk_size:
                out.append({"index": idx, "content": part, "start": 0, "end": 0})
                idx += 1
            else:
                for sub in ChunkingStrategies.fixed(part, max_chunk_size, ChunkingStrategies.DEFAULT_OVERLAP):
                    out.append({"index": idx, "content": sub["content"], "start": 0, "end": 0})
                    idx += 1
        return out

    @staticmethod
    def hierarchical(content: str, max_chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[dict]:
        """Same as semantic but tracks parent heading level (informational)."""
        chunks = ChunkingStrategies.semantic(content, max_chunk_size)
        for c in chunks:
            first_line = (c["content"].splitlines() or [""])[0]
            m = re.match(r"^(#{1,6})\s", first_line)
            c["level"] = len(m.group(1)) if m else 0
        return chunks


@dataclass
class Chunk:
    id: str
    memory_id: str
    index: int
    content: str
    hash: str
    created_at: str
    embedding: list[float] | None = None
    parent: str | None = None
    level: int = 0
    metadata: dict = field(default_factory=dict)


class ChunkStore:
    def __init__(self, event_bus=None) -> None:
        self.event_bus = event_bus
        self.chunks: dict[str, Chunk] = {}
        self.memory_chunks: dict[str, list[str]] = {}

    def chunk_content(self, content: str, strategy: str = "semantic") -> list[dict]:
        if strategy == "fixed":
            return ChunkingStrategies.fixed(content)
        if strategy == "paragraph":
            return ChunkingStrategies.paragraph(content)
        if strategy == "hierarchical":
            return ChunkingStrategies.hierarchical(content)
        return ChunkingStrategies.semantic(content)

    def store_chunks(self, memory_id: str, chunks_data: list[dict], embeddings: list[list[float]] | None = None) -> list[Chunk]:
        stored: list[Chunk] = []
        ids: list[str] = []
        for i, c in enumerate(chunks_data):
            cid = f"{memory_id}__{i}"
            ids.append(cid)
            text = c["content"]
            h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            embedding = embeddings[i] if embeddings and i < len(embeddings) else None
            chunk = Chunk(
                id=cid,
                memory_id=memory_id,
                index=i,
                content=text,
                hash=h,
                created_at=now_iso(),
                embedding=embedding,
                level=c.get("level", 0),
                metadata={
                    "start": c.get("start", 0),
                    "end": c.get("end", 0),
                    "charCount": len(text),
                    "wordCount": len(text.split()),
                },
            )
            self.chunks[cid] = chunk
            stored.append(chunk)
            if self.event_bus:
                self.event_bus.publish("chunk:created", chunk)
        self.memory_chunks[memory_id] = ids
        return stored

    def get_memory_chunks(self, memory_id: str) -> list[Chunk]:
        return [self.chunks[cid] for cid in self.memory_chunks.get(memory_id, [])]

    def delete_memory_chunks(self, memory_id: str) -> None:
        for cid in self.memory_chunks.pop(memory_id, []):
            self.chunks.pop(cid, None)

    def clear(self) -> None:
        self.chunks.clear()
        self.memory_chunks.clear()