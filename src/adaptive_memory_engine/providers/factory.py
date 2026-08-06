"""Provider factory — builds embedding + intelligence providers from a Config."""
from __future__ import annotations

import logging

from ..config import Config
from .anthropic_provider import AnthropicProvider
from .base import EmbeddingProvider, IntelligentProvider
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider

log = logging.getLogger(__name__)


class ProviderFactory:
    """Build embedding + intelligence providers from a Config."""

    @staticmethod
    def create(cfg: Config) -> tuple[EmbeddingProvider, IntelligentProvider | None]:
        """Returns (embedding_provider, intelligence_provider_or_None)."""
        emb = ProviderFactory._build_embedding(cfg)
        if not emb.is_available():
            raise RuntimeError(
                f"Embedding provider '{cfg.provider_type}' is not available. "
                "Check your API key and connectivity."
            )
        intel = ProviderFactory._build_intelligence(cfg, emb)
        return emb, intel

    @staticmethod
    def _build_embedding(cfg: Config) -> EmbeddingProvider:
        t = cfg.provider_type
        if t == "openai":
            return OpenAIProvider(
                api_key=cfg.openai_api_key,
                base_url=cfg.openai_base_url,
                embedding_model=cfg.openai_embedding_model,
                chat_model=cfg.openai_chat_model,
            )
        if t == "ollama":
            return OllamaProvider(
                host=cfg.ollama_host,
                embedding_model=cfg.ollama_embedding_model,
                chat_model=cfg.ollama_chat_model,
            )
        if t == "gemini":
            return GeminiProvider(api_key=cfg.gemini_api_key)
        if t == "anthropic":
            # Anthropic has no embeddings — use OpenAI as fallback if available, else Ollama.
            fallback = (
                OpenAIProvider(
                    api_key=cfg.openai_api_key,
                    base_url=cfg.openai_base_url,
                    embedding_model=cfg.openai_embedding_model,
                    chat_model=cfg.openai_chat_model,
                )
                if cfg.openai_api_key
                else OllamaProvider(
                    host=cfg.ollama_host,
                    embedding_model=cfg.ollama_embedding_model,
                    chat_model=cfg.ollama_chat_model,
                )
            )
            return fallback
        raise ValueError(f"Unknown PROVIDER_TYPE: {t}")

    @staticmethod
    def _build_intelligence(
        cfg: Config, embedding: EmbeddingProvider
    ) -> IntelligentProvider | None:
        """If INTELLIGENCE_PROVIDER set, build that as intelligent provider.
        Otherwise upgrade the embedding provider to IntelligentProvider if it is one."""
        target = (cfg.intelligence_provider or cfg.provider_type).lower()
        if target == "openai":
            return OpenAIProvider(
                api_key=cfg.openai_api_key,
                base_url=cfg.openai_base_url,
                embedding_model=cfg.openai_embedding_model,
                chat_model=cfg.openai_chat_model,
            )
        if target == "ollama":
            return OllamaProvider(
                host=cfg.ollama_host,
                embedding_model=cfg.ollama_embedding_model,
                chat_model=cfg.ollama_chat_model,
            )
        if target == "gemini":
            return GeminiProvider(api_key=cfg.gemini_api_key)
        if target == "anthropic":
            if not cfg.anthropic_api_key:
                log.warning("ANTHROPIC_API_KEY missing — AI features disabled.")
                return None
            return AnthropicProvider(
                api_key=cfg.anthropic_api_key,
                embedding_fallback=embedding,
            )
        # Fallback: use embedding if it happens to be intelligent
        if isinstance(embedding, IntelligentProvider):
            return embedding
        return None