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
    storage_backend: str = "sqlite"
    database_url: str | None = None
    database_pool_min: int = 1
    database_pool_max: int = 10

    # Server
    port: int = 3000
    transport: str = "stdio"  # "stdio" | "http"  (auto: http on PaaS)
    auth_token: str | None = None
    allowed_origins: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    import_root: str | None = None

    # Embedding dims (auto-derived per provider)
    embedding_dims: int = 1536

    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, env_file: str | None = None) -> Config:
        env = _load_env_file(env_file)
        # Merge: explicit process env wins, then .env, then defaults.
        merged = {**env, **os.environ}

        port_present = "PORT" in merged
        try:
            port = int(merged.get("PORT", "3000"))
        except ValueError as exc:
            raise ValueError("PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("PORT must be between 1 and 65535")

        provider = (merged.get("PROVIDER_TYPE") or "openai").lower()
        transport = (
            merged.get("TRANSPORT", "").lower()
            if merged.get("TRANSPORT")
            else ("http" if port_present else "stdio")
        )
        if transport not in {"stdio", "http"}:
            raise ValueError("TRANSPORT must be 'stdio' or 'http'")
        auth_token = merged.get("AUTH_TOKEN")
        if auth_token and len(auth_token.encode("utf-8")) < 32:
            raise ValueError("AUTH_TOKEN must be at least 32 bytes")

        database_url = merged.get("DATABASE_URL")
        storage_backend = (merged.get("STORAGE_BACKEND") or ("postgres" if database_url else "sqlite")).lower()
        if storage_backend not in {"sqlite", "postgres"}:
            raise ValueError("STORAGE_BACKEND must be 'sqlite' or 'postgres'")
        if storage_backend == "postgres" and not database_url:
            raise ValueError("DATABASE_URL is required when STORAGE_BACKEND=postgres")
        try:
            pool_min = int(merged.get("DATABASE_POOL_MIN", "1"))
            pool_max = int(merged.get("DATABASE_POOL_MAX", "10"))
        except ValueError as exc:
            raise ValueError("DATABASE_POOL_MIN and DATABASE_POOL_MAX must be integers") from exc
        if pool_min < 1 or pool_max < pool_min or pool_max > 100:
            raise ValueError("database pool sizes must satisfy 1 <= min <= max <= 100")

        def csv_values(name: str, defaults: list[str]) -> list[str]:
            raw = merged.get(name)
            return [v.strip() for v in raw.split(",") if v.strip()] if raw else defaults

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
            storage_backend=storage_backend,
            database_url=database_url,
            database_pool_min=pool_min,
            database_pool_max=pool_max,
            port=port,
            transport=transport,
            auth_token=auth_token,
            allowed_origins=csv_values("ALLOWED_ORIGINS", []),
            allowed_hosts=csv_values("ALLOWED_HOSTS", []),
            import_root=merged.get("IMPORT_ROOT"),
        )
        # Never retain the full process environment: it often contains unrelated
        # credentials and Config.extra is not used by the application.
        cfg.extra = {}
        return cfg

    def ensure_data_dir(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
