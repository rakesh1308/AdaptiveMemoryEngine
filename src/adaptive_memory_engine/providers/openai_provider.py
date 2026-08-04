"""OpenAI provider (chat + embeddings)."""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

import httpx

from .base import IntelligentProvider

log = logging.getLogger(__name__)


class OpenAIProvider(IntelligentProvider):
    name = "openai"
    dimensions = 1536  # text-embedding-3-small

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.openai.com/v1",
        embedding_model: str = "text-embedding-3-small",
        chat_model: str = "gpt-4o-mini",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.embedding_model = embedding_model
        self.chat_model = chat_model
        self._client = httpx.Client(timeout=timeout)

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def embed(self, text: str) -> list[float]:
        text = self._clean_text(text)
        r = self._client.post(
            f"{self.base_url}/embeddings",
            headers=self._headers(),
            json={"input": text, "model": self.embedding_model},
        )
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]

    def embed_batch(self, texts: Iterable[str]) -> list[list[float]]:
        cleaned = [self._clean_text(t) for t in texts]
        out: list[list[float]] = []
        batch_size = 20
        for i in range(0, len(cleaned), batch_size):
            chunk = cleaned[i : i + batch_size]
            r = self._client.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                json={"input": chunk, "model": self.embedding_model},
            )
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        return out

    def auto_tag(self, key: str, content: str) -> list[str]:
        prompt = (
            "Generate 3-5 concise, lowercase tags for the following content. "
            "Return ONLY a JSON array of strings, no other text.\n\n"
            f"Key: {key}\nContent: {self._clean_text(content)[:1500]}\nTags:"
        )
        text = self._chat(prompt, json_mode=True)
        return self._parse_tag_list(text)

    def synthesize(self, content: str, task: str, style: str = "concise") -> str:
        prompt = (
            f"Task: {task}\nStyle: {style}\n\n"
            f"Content:\n{self._clean_text(content)[:6000]}\n\nResponse:"
        )
        return self._chat(prompt)

    def expand_query(self, query: str) -> list[str]:
        prompt = (
            "Given the user query, generate 3 paraphrases that mean the same thing. "
            "Return ONLY a JSON array of strings.\n\n"
            f"Query: {query}\nParaphrases:"
        )
        text = self._chat(prompt, json_mode=True)
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                return [str(x) for x in arr]
        except Exception:  # noqa: BLE001
            pass
        return [query]

    def get_config(self) -> dict:
        return {
            "type": "openai",
            "embeddingModel": self.embedding_model,
            "chatModel": self.chat_model,
            "baseUrl": self.base_url,
        }

    # ---- internals ----

    def _chat(self, prompt: str, json_mode: bool = False) -> str:
        body: dict = {
            "model": self.chat_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = self._client.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=body,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        # Match Node: collapse whitespace, cap at 8000 chars
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned[:8000]

    def _parse_tag_list(self, text: str) -> list[str]:
        try:
            arr = json.loads(text)
            if isinstance(arr, dict):
                arr = arr.get("tags", [])
            if isinstance(arr, list):
                return [str(t).strip().lower() for t in arr if str(t).strip()][:10]
        except Exception:  # noqa: BLE001
            log.debug("auto_tag JSON parse failed, falling back to regex")
        # Fallback: extract quoted strings
        return [m.group(1).lower() for m in re.finditer(r'"([^"]+)"', text)][:10]