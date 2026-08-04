"""Google Gemini provider."""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

import httpx

from .base import IntelligentProvider

log = logging.getLogger(__name__)


class GeminiProvider(IntelligentProvider):
    name = "gemini"
    dimensions = 768

    def __init__(
        self,
        api_key: str | None,
        embedding_model: str = "text-embedding-004",
        chat_model: str = "gemini-1.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def is_available(self) -> bool:
        return bool(self.api_key)

    def embed(self, text: str) -> list[float]:
        url = (
            f"{self.base_url}/models/{self.embedding_model}:embedContent"
            f"?key={self.api_key}"
        )
        r = self._client.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "content": {"parts": [{"text": text[:8000]}]},
            },
        )
        r.raise_for_status()
        return r.json()["embedding"]["values"]

    def embed_batch(self, texts: Iterable[str]) -> list[list[float]]:
        url = (
            f"{self.base_url}/models/{self.embedding_model}:batchEmbedContents"
            f"?key={self.api_key}"
        )
        reqs = [
            {
                "model": f"models/{self.embedding_model}",
                "content": {"parts": [{"text": t[:8000]}]},
            }
            for t in texts
        ]
        r = self._client.post(
            url,
            headers={"Content-Type": "application/json"},
            json={"requests": reqs},
        )
        r.raise_for_status()
        return [e["values"] for e in r.json()["embeddings"]]

    def auto_tag(self, key: str, content: str) -> list[str]:
        prompt = (
            "Generate 3-5 concise lowercase tags as JSON array of strings.\n\n"
            f"Key: {key}\nContent: {content[:1500]}\nTags:"
        )
        text = self._generate(prompt)
        return self._parse_tag_list(text)

    def synthesize(self, content: str, task: str, style: str = "concise") -> str:
        prompt = f"Task: {task}\nStyle: {style}\n\nContent:\n{content[:6000]}\n\nResponse:"
        return self._generate(prompt)

    def expand_query(self, query: str) -> list[str]:
        prompt = (
            "Generate 3 paraphrases as JSON array of strings.\n\n"
            f"Query: {query}\nParaphrases:"
        )
        text = self._generate(prompt)
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                return [str(x) for x in arr]
        except Exception:  # noqa: BLE001
            pass
        return [query]

    def get_config(self) -> dict:
        return {
            "type": "gemini",
            "embeddingModel": self.embedding_model,
            "chatModel": self.chat_model,
        }

    def _generate(self, prompt: str) -> str:
        url = (
            f"{self.base_url}/models/{self.chat_model}:generateContent"
            f"?key={self.api_key}"
        )
        r = self._client.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            },
        )
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def _parse_tag_list(self, text: str) -> list[str]:
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                return [str(t).strip().lower() for t in arr if str(t).strip()][:10]
        except Exception:  # noqa: BLE001
            pass
        return [m.group(1).lower() for m in re.finditer(r'"([^"]+)"', text)][:10]