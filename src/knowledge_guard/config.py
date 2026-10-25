"""Runtime configuration.

Context: Every setting comes from environment variables or .env; nothing is hard-coded in
the modules. | Input: environment. | Output: cached, validated Settings.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO_TOKEN_SECRET = "demo-only-change-me"  # noqa: S105 - documented demo default

EmbeddingProvider = Literal["openai", "local"]
LlmProvider = Literal["anthropic", "openai", "none"]


class Settings(BaseSettings):
    """Validated settings of the API service."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_database_url: str = "postgresql://kg_app:kg_app_pw@localhost:5433/knowledge_guard"
    owner_database_url: str = "postgresql://kg_owner:kg_owner_pw@localhost:5433/knowledge_guard"
    pool_max_size: int = Field(default=10, ge=1, le=100)
    database_wait_seconds: float = Field(default=90.0, gt=0)

    token_secret: SecretStr = SecretStr(DEMO_TOKEN_SECRET)
    token_ttl_seconds: int = Field(default=8 * 3600, gt=0)

    embedding_provider: Literal["auto", "openai", "local"] = "auto"
    openai_embedding_model: str = "text-embedding-3-small"

    llm_provider: Literal["auto", "anthropic", "openai", "none"] = "auto"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    llm_timeout: float = Field(default=60.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0, le=10)

    top_k: int = Field(default=5, ge=1, le=50)
    show_blocked_count: bool = True
    grant_days_default: int = Field(default=14, ge=1, le=365)
    seed_on_start: bool = True

    @property
    def uses_demo_secret(self) -> bool:
        return self.token_secret.get_secret_value() == DEMO_TOKEN_SECRET

    def resolved_embedding_provider(self) -> EmbeddingProvider:
        """OpenAI when configured or a key exists, otherwise the built-in local embedding."""
        if self.embedding_provider == "auto":
            return "openai" if _has(self.openai_api_key) else "local"
        return self.embedding_provider

    def resolved_llm_provider(self) -> LlmProvider:
        """First provider with a key, or 'none' for the extractive mode."""
        if self.llm_provider != "auto":
            return self.llm_provider
        if _has(self.anthropic_api_key):
            return "anthropic"
        if _has(self.openai_api_key):
            return "openai"
        return "none"


def _has(secret: SecretStr | None) -> bool:
    return bool(secret and secret.get_secret_value().strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings of this process, read once."""
    return Settings()
