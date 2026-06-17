"""Configuration loaded from environment / .env (KTD8, KTD8a, KTD9).

All secrets, model names, thresholds and budgets live here, never hard-coded.
Switching OpenAI <-> OpenRouter is a base_url + key change (KTD8a).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    telegram_bot_token: str

    # --- LLM (OpenAI-compatible; OpenRouter = swap base_url + key, KTD8a) ---
    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    llm_triage_model: str = "gpt-4.1-nano"
    llm_extract_model: str = "gpt-4.1-mini"
    llm_answer_model: str = "gpt-4.1-mini"
    llm_embed_model: str = "text-embedding-3-small"

    # --- Storage ---
    db_path: str = "./data/secretary.db"
    kb_local_path: str = "./data/kb"
    chroma_path: str = "./data/chroma"

    # --- KB repo (must be private; KTD4) ---
    kb_repo_url: str | None = None
    kb_repo_token: str | None = None
    kb_repo_deploy_key_path: str | None = None

    # --- Access / admin (KTD6) ---
    admin_user_id: int | None = None
    membership_ttl_seconds: int = 3600

    # --- Pipeline thresholds ---
    confidence_threshold: float = 0.5
    dup_similarity_threshold: float = 0.90
    relevance_similarity_threshold: float = 0.30

    # --- Cadence & budgets (KTD2, KTD10) ---
    extract_message_threshold: int = 50
    extract_budget_per_chat: int = 1000
    extract_budget_global: int = 10000
    query_rate_limit_per_min: int = 10
    scan_interval_seconds: int = 300
    budget_period_seconds: int = 3600

    # --- Behaviour flags ---
    leave_unsanctioned_chats: bool = False


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance."""
    return Settings()  # type: ignore[call-arg]
