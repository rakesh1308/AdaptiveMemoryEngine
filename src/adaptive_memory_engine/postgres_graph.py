"""Knowledge graph persisted in normalized PostgreSQL tables."""

from __future__ import annotations

from pathlib import Path

from .knowledge_graph import KnowledgeGraph, normalize_concept


class PostgresKnowledgeGraph(KnowledgeGraph):
    def __init__(self, backend, data_dir: str | Path, event_bus=None) -> None:
        self.backend = backend
        super().__init__(data_dir, event_bus=event_bus)

    def _load(self) -> None:
        if self.backend._pool is None:
            return
        concepts, relationships, concept_index = self.backend.load_graph()
        self.concepts.clear()
        self.relationships.clear()
        self.concept_index.clear()
        self.concepts.update(concepts)
        self.relationships.extend(relationships)
        self._relationship_by_id = {
            relationship["id"]: relationship for relationship in relationships
        }
        self.concept_index.update(concept_index)

    def save(self) -> None:
        self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = False

    def autosave_tick(self) -> None:
        return None

    def add_concept(self, name: str, memory_id: str | None = None) -> str:
        concept_id = super().add_concept(name, memory_id)
        if concept_id:
            self.backend.upsert_graph_concept(self.concepts[concept_id], memory_id)
        return concept_id

    def add_relationship(
        self,
        from_concept: str,
        to_concept: str,
        rel_type: str = "related_to",
        memory_id: str | None = None,
        strength: float = 0.5,
    ) -> None:
        super().add_relationship(from_concept, to_concept, rel_type, memory_id, strength)
        left = normalize_concept(from_concept)
        right = normalize_concept(to_concept)
        relation_id = f"{left}__{rel_type}__{right}"
        relationship = self._relationship_by_id.get(relation_id)
        if relationship:
            self.backend.upsert_graph_relationship(relationship)

    def delete_memory(self, memory_id: str) -> None:
        super().delete_memory(memory_id)
        self.backend.delete_graph_memory(memory_id)
