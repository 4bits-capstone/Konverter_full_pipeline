"""RAG configuration. Provider, model and dimension come from the environment, never from code paths.

Importing app.config first lets a developer's root .env fill os.environ exactly as it does for the
API (it is skipped under pytest). Nothing here reads, prints or logs secret values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .. import config as _app_config  # noqa: F401  (side effect: loads the root .env outside tests)

# Defaults used only when RAG_EMBED_MODEL is unset. The final choice is still open.
_DEFAULT_MODEL = {"voyage": "voyage-law-2", "openai": "text-embedding-3-small"}
_PROVIDERS = tuple(_DEFAULT_MODEL)
_BACKEND = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RagSettings:
    embed_provider: str = "voyage"
    embed_model: str = "voyage-law-2"
    embed_dim: int = 1024
    embed_batch: int = 64
    max_chars: int = 2500
    voyage_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    supabase_url: str = ""
    supabase_key: str = field(default="", repr=False)
    cache_dir: Path = _BACKEND / "runtime" / "rag-cache"

    @property
    def embed_fingerprint(self) -> str:
        """Identifies the vector space a stored embedding lives in."""
        return f"{self.embed_provider}:{self.embed_model}:{self.embed_dim}"


def load_rag_settings(env: Mapping[str, str] | None = None) -> RagSettings:
    env = os.environ if env is None else env

    def get(name: str, default: str = "") -> str:
        return (env.get(name) or default).strip()

    provider = get("RAG_EMBED_PROVIDER", "voyage").lower()
    if provider not in _PROVIDERS:
        raise ConfigError(f"RAG_EMBED_PROVIDER must be one of {', '.join(_PROVIDERS)} (got {provider!r})")
    try:
        dim = int(get("RAG_EMBED_DIM", "1024"))
        batch = int(get("RAG_EMBED_BATCH", "64"))
        max_chars = int(get("RAG_CHUNK_MAX_CHARS", "2500"))
    except ValueError as exc:
        raise ConfigError("RAG_EMBED_DIM, RAG_EMBED_BATCH and RAG_CHUNK_MAX_CHARS must be integers") from exc
    if not 1 <= dim <= 2000:
        raise ConfigError("RAG_EMBED_DIM must be between 1 and 2000 (the pgvector index limit)")
    if batch < 1 or max_chars < 200:
        raise ConfigError("RAG_EMBED_BATCH must be >= 1 and RAG_CHUNK_MAX_CHARS >= 200")
    return RagSettings(
        embed_provider=provider,
        embed_model=get("RAG_EMBED_MODEL", _DEFAULT_MODEL[provider]),
        embed_dim=dim,
        embed_batch=batch,
        max_chars=max_chars,
        voyage_api_key=get("VOYAGE_API_KEY"),
        openai_api_key=get("OPENAI_API_KEY"),
        supabase_url=get("SUPABASE_URL").rstrip("/"),
        supabase_key=get("SUPABASE_SERVICE_ROLE_KEY"),
        cache_dir=Path(get("RAG_CACHE_DIR")) if get("RAG_CACHE_DIR") else _BACKEND / "runtime" / "rag-cache",
    )
