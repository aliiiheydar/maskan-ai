"""Deployment/environment settings, sourced from .env (see .env.example)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # One provider for everything: chat/intent completions and embeddings are
    # both served from the OPENROUTER_* account. A second chat provider was
    # tried and removed -- it ran a content filter that rejected any message
    # with five or more non-ASCII characters, which is every Persian turn this
    # product makes.
    openrouter_api_key: str = "your_openrouter_api_key_here"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "deepseek/deepseek-chat"
    embedding_model: str = "openai/text-embedding-3-small"
    default_lat: float = 35.6997
    default_lon: float = 51.3380
    app_env: str = "development"
    debug: bool = True


settings = Settings()
