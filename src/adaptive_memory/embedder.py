"""Local embeddings via fastembed (ONNX). No API key, no network after the first model download."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

# Keep the MCP stdio stream quiet: no progress bars or symlink warnings on first download.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BAR", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"  # 384 dims, ~130 MB
MAX_CHARS = 2000  # the model reads ~512 tokens; keyword search still covers the full text


def data_dir() -> Path:
    return Path(os.environ.get("ADAPTIVE_MEMORY_HOME", Path.home() / ".adaptive-memory"))


class Embedder:
    """Loads the model lazily so the MCP server starts instantly."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("ADAPTIVE_MEMORY_MODEL", DEFAULT_MODEL)
        self._engine = None

    def _load(self):
        if self._engine is None:
            from fastembed import TextEmbedding

            cache = data_dir() / "models"
            cache.mkdir(parents=True, exist_ok=True)
            self._engine = TextEmbedding(model_name=self.model, cache_dir=str(cache))
        return self._engine

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.array(list(self._load().embed([t[:MAX_CHARS] for t in texts])), dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.where(norms == 0, 1, norms)
