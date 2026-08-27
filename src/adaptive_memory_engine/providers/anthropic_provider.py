"""Anthropic provider (chat only — embeddings require a fallback)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable

import httpx

from .base import EmbeddingProvider, IntelligentProvider
from .http import request_with_retry

log = logging.getLogger(__name__)


class AnthropicProvider(IntelligentProvider):
    name = "anthropic"
    dimensions = 1536  # virtual; we delegate embedding to fallback

    def __init__(
        self,
        api_key: str | None,
        embedding_fallback: EmbeddingProvider,
        base_url: str = "https://api.anthropic.com/v1",
        chat_model: str = "claude-haiku-4-5-20251001",
        embedding_model: str = "claude-haiku-4-5-20251001",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self._fallback = embedding_fallback
        self._client = httpx.Client(timeout=timeout)
        # Use the fallback's true dimensions
        if hasattr(embedding_fallback, "dimensions"):
            self.dimensions = embedding_fallback.dimensions

    def is_available(self) -> bool:
        return bool(self.api_key) and self._fallback.is_available()

    def embed(self, text: str) -> list[float]:
        return self._fallback.embed(text)

    def embed_batch(self, texts: Iterable[str]) -> list[list[float]]:
        return self._fallback.embed_batch(texts)

    def auto_tag(self, key: str, content: str) -> list[str]:
        text = self._messages(
            "Generate 3-5 concise lowercase tags as a JSON array of strings. "
            "Reply with JSON only.\n\n"
            f"Key: {key}\nContent: {content[:1500]}\nTags:"
        )
        return self._parse_tag_list(text)

    def synthesize(self, content: str, task: str, style: str = "concise") -> str:
        return self._messages(
            f"Task: {task}\nStyle: {style}\n\nContent:\n{content[:6000]}\n\nResponse:"
        )

    def expand_query(self, query: str) -> list[str]:
        text = self._messages(
            f"Generate 3 paraphrases as a JSON array of strings.\n\nQuery: {query}\nParaphrases:"
        )
        try:
            arr = json.loads(text)
            if isinstance(arr, dict):
                arr = arr.get("queries") or arr.get("paraphrases") or []
            if isinstance(arr, list):
                return [str(x) for x in arr]
        except Exception:  # noqa: BLE001
            pass
        return [query]

    def get_config(self) -> dict:
        return {
            "type": "anthropic",
            "chatModel": self.chat_model,
            "embeddingFallback": getattr(self._fallback, "name", "unknown"),
        }

    def _messages(self, prompt: str) -> str:
        r = request_with_retry(
            self._client,
            "POST",
            f"{self.base_url}/messages",
            headers={
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.chat_model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        content = r.json()["content"]
        return "".join(b.get("text", "") for b in content if b.get("type") == "text")

    def close(self) -> None:
        self._client.close()

    def _parse_tag_list(self, text: str) -> list[str]:
        try:
            arr = json.loads(text)
            if isinstance(arr, dict):
                arr = arr.get("tags", [])
            if isinstance(arr, list):
                return [str(t).strip().lower() for t in arr if str(t).strip()][:10]
        except Exception:  # noqa: BLE001
            pass
        return [m.group(1).lower() for m in re.finditer(r'"([^"]+)"', text)][:10]
