"""Vector-search adapter backed by PostgreSQL pgvector."""

from __future__ import annotations

from .vector_store import VectorEntry


class PgVectorStore:
    def __init__(self, backend, embedding_provider) -> None:
        self.backend = backend
        self.embedding_provider = embedding_provider
        self.dimensions = backend.dimensions

    def clear(self) -> None:
        # PostgreSQL is persistent; initialization must never erase its index.
        return None

    def add(self, entry_id: str, vector: list[float], metadata: dict | None = None) -> None:
        # Chunks are transactionally persisted by PostgresBackend.save_chunks().
        return None

    def remove(self, entry_id: str) -> None:
        return None

    def remove_memory(self, memory_id: str) -> None:
        self.backend.delete_embedding(memory_id)

    def get(self, entry_id: str) -> None:
        return None

    def search(
        self, query_vector: list[float], top_k: int = 10, min_score: float = 0.0
    ) -> list[tuple[VectorEntry, float]]:
        rows = self.backend.search_vectors(query_vector, max(top_k * 5, 50))
        return [
            (
                VectorEntry(
                    id=row["id"],
                    vector=[],
                    metadata={"memoryId": row["memory_id"], "chunkIndex": row["chunk_index"]},
                ),
                float(row["score"]),
            )
            for row in rows
            if float(row["score"]) >= min_score
        ][:top_k]

    def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        keyword_results: list[str],
        top_k: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[tuple[VectorEntry, float]]:
        semantic = self.search(query_vector, top_k=max(top_k * 5, 50))
        keyword_rank = {memory_id: i for i, memory_id in enumerate(keyword_results)}
        by_memory: dict[str, tuple[VectorEntry, float]] = {}
        for entry, semantic_score in semantic:
            memory_id = entry.metadata["memoryId"]
            rank = keyword_rank.get(memory_id)
            keyword_score = 0.0 if rank is None else 1.0 - rank / max(len(keyword_results), 1)
            score = semantic_weight * semantic_score + keyword_weight * keyword_score
            previous = by_memory.get(memory_id)
            if previous is None or score > previous[1]:
                by_memory[memory_id] = (entry, score)
        return sorted(by_memory.values(), key=lambda item: item[1], reverse=True)[:top_k]

    def cached_embed(self, text: str) -> list[float]:
        return self.embedding_provider.embed(text)
