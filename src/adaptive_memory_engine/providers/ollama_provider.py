"""Ollama provider (local / private)."""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

import httpx

from .base import IntelligentProvider

log = logging.getLogger(__name__)


class OllamaProvider(IntelligentProvider):
    name = "ollama"
    dimensions = 768

    def __init__(
        self,
        host: str = "http://localhost:11434",
        embedding_model: str = "nomic-embed-text",
        chat_model: str = "llama3.2",
        timeout: float = 120.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self._client = httpx.Client(timeout=timeout)

    def is_available(self) -> bool:
        try:
            r = self._client.get(f"{self.host}/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def embed(self, text: str) -> list[float]:
        r = self._client.post(
            f"{self.host}/api/embeddings",
            json={"model": self.embedding_model, "prompt": text[:8000]},
        )
        r.raise_for_status()
        return r.json()["embedding"]

    def embed_batch(self, texts: Iterable[str]) -> list[list[float]]:
        # Ollama has no native batch endpoint; sequential
        return [self.embed(t) for t in texts]

    def auto_tag(self, key: str, content: str) -> list[str]:
        prompt = (
            "Generate 3-5 concise, lowercase tags as a JSON array of strings.\n\n"
            f"Key: {key}\nContent: {content[:1500]}\nTags:"
        )
        text = self._generate(prompt, fmt="json")
        return self._parse_tag_list(text)

    def synthesize(self, content: str, task: str, style: str = "concise") -> str:
        prompt = f"Task: {task}\nStyle: {style}\n\nContent:\n{content[:6000]}\n\nResponse:"
        return self._generate(prompt)

    def expand_query(self, query: str) -> list[str]:
        prompt = (
            "Generate 3 paraphrases as a JSON array of strings.\n\n"
            f"Query: {query}\nParaphrases:"
        )
        text = self._generate(prompt, fmt="json")
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                return [str(x) for x in arr]
        except Exception:  # noqa: BLE001
            pass
        return [query]

    def get_config(self) -> dict:
        return {
            "type": "ollama",
            "host": self.host,
            "embeddingModel": self.embedding_model,
            "chatModel": self.chat_model,
        }

    def _generate(self, prompt: str, fmt: str | None = None) -> str:
        body: dict = {"model": self.chat_model, "prompt": prompt, "stream": False}
        if fmt:
            body["format"] = fmt
        r = self._client.post(f"{self.host}/api/generate", json=body)
        r.raise_for_status()
        return r.json()["response"]

    def _parse_tag_list(self, text: str) -> list[str]:
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                return [str(t).strip().lower() for t in arr if str(t).strip()][:10]
        except Exception:  # noqa: BLE001
            pass
        return [m.group(1).lower() for m in re.finditer(r'"([^"]+)"', text)][:10]