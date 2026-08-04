"""Configuration loaded from environment / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, find_dotenv


def _load_env_file(path: str | None) -> dict[str, str]:
    """Load .env without overriding already-set process env vars."""
    if not path:
        dotenv_path = find_dotenv(usecwd=True)
        if not dotenv_path:
            return {}
        path = dotenv_path
    raw = dotenv_values(path)
    out: dict[str, str] = {}
    for k, v in raw.items():
        if v is None:
            continue
        if not v or "YOUR-KEY-HERE" in v or v.endswith("****"):
            continue
        if k not in os.environ:
            out[k] = v
    return out


@dataclass
class Config:
    # Provider
    provider_type: str = "openai"
    intelligence_provider: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"
    ollama_host: str = "http://localhost:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_chat_model: str = "llama3.2"
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None

    # Storage
    data_dir: str = "./data"

    # Server
    port: int = 3000
    transport: str = "stdio"  # "stdio" | "http"  (auto: http on PaaS)

    # Embedding dims (auto-derived per provider)
    embedding_dims: int = 1536

    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, env_file: str | None = None) -> "Config":
        env = _load_env_file(env_file)
        # Merge: explicit process env wins, then .env, then defaults.
        merged = {**env, **os.environ}

        port_present = "PORT" in merged
        port = int(merged.get("PORT", "3000"))

        provider = (merged.get("PROVIDER_TYPE") or "openai").lower()

        cfg = cls(
            provider_type=provider,
            intelligence_provider=merged.get("INTELLIGENCE_PROVIDER"),
            openai_api_key=merged.get("OPENAI_API_KEY"),
            openai_base_url=merged.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_embedding_model=merged.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            openai_chat_model=merged.get("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
            ollama_host=merged.get("OLLAMA_HOST", "http://localhost:11434"),
            ollama_embedding_model=merged.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
            ollama_chat_model=merged.get("OLLAMA_CHAT_MODEL", "llama3.2"),
            gemini_api_key=merged.get("GEMINI_API_KEY"),
            anthropic_api_key=merged.get("ANTHROPIC_API_KEY"),
            data_dir=merged.get("DATA_DIR") or ("/data" if port_present else "./data"),
            port=port,
            transport=(
                merged.get("TRANSPORT").lower()
                if merged.get("TRANSPORT")
                else ("http" if port_present else "stdio")
            ),
        )
        cfg.extra = {k: v for k, v in merged.items() if k not in {
            "PROVIDER_TYPE", "INTELLIGENCE_PROVIDER", "OPENAI_API_KEY", "OPENAI_BASE_URL",
            "OPENAI_EMBEDDING_MODEL", "OPENAI_CHAT_MODEL", "OLLAMA_HOST",
            "OLLAMA_EMBEDDING_MODEL", "OLLAMA_CHAT_MODEL", "GEMINI_API_KEY",
            "ANTHROPIC_API_KEY", "DATA_DIR", "TRANSPORT", "PORT",
        }}
        return cfg

    def ensure_data_dir(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p