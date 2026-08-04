"""Lightweight event bus + stable event names matching the Node version."""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)


class MemoryEvents:
    MEMORY_CREATED = "memory:created"
    MEMORY_UPDATED = "memory:updated"
    MEMORY_DELETED = "memory:deleted"
    MEMORY_ACCESSED = "memory:accessed"
    MEMORY_ARCHIVED = "memory:archived"
    MEMORY_RESTORED = "memory:restored"
    CHUNK_CREATED = "chunk:created"
    CHUNK_EMBEDDED = "chunk:embedded"
    CONCEPT_EXTRACTED = "concept:extracted"
    RELATIONSHIP_ADDED = "relationship:added"
    GRAPH_UPDATED = "graph:updated"
    IMPORTANCE_UPDATED = "importance:updated"
    DECAY_APPLIED = "decay:applied"
    CONSOLIDATION_RUN = "consolidation:run"
    BACKUP_CREATED = "backup:created"
    ERROR_OCCURRED = "error:occurred"


class EventBus:
    """Tiny synchronous pub/sub. Mirrors the Node bus used by the lifecycle layer."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[str, Any], None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event: str, handler: Callable[[str, Any], None]) -> None:
        with self._lock:
            self._subs[event].append(handler)

    def publish(self, event: str, payload: Any = None) -> None:
        handlers = list(self._subs.get(event, []))
        for h in handlers:
            try:
                h(event, payload)
            except Exception:  # noqa: BLE001
                log.exception("Event handler error for %s", event)

    def unsubscribe(self, event: str, handler: Callable[[str, Any], None]) -> None:
        with self._lock:
            if handler in self._subs.get(event, []):
                self._subs[event].remove(handler)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"


def gen_id(prefix: str = "") -> str:
    """Match Node's `${Date.now()}-${rand36(9)}`."""
    import secrets
    rand36 = "".join(
        secrets.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(9)
    )
    return f"{prefix}{int(time.time() * 1000)}-{rand36}"