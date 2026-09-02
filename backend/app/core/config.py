"""Deployment/environment settings, sourced from backend/.env.

See backend/.env.example for a documented development file and
backend/.env.production.example for a deployment one. Real environment
variables take precedence over the file, which is how the compose files
override DB_PATH without editing anything.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import paths


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # An absolute path, not ".env" relative to the working directory.
        # This is read once at import, and a process started from the
        # repository root -- a reloader worker, a script, a one-off `python -c`
        # -- would otherwise find no file, fall back to every default, and
        # report a configured deployment as unconfigured. Where uvicorn was
        # launched from is not something the configuration should depend on.
        env_file=paths.BACKEND_DIR / ".env",
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
    # The leading ~ belongs to the OpenRouter id: it marks a floating "latest"
    # alias rather than a pinned dated build.
    llm_model: str = "~deepseek/deepseek-v4-flash-latest"
    embedding_model: str = "openai/text-embedding-3-small"
    default_lat: float = 35.6997
    default_lon: float = 51.3380
    # کاوش نقشه: the free-roam map that returns whatever is inside the
    # viewport and ignores the filter panel. A deployment that wants the
    # filters to be the only way in can turn it off, and the header then drops
    # the mode entirely rather than showing a control that goes nowhere.
    explore_map_enabled: bool = True
    app_env: str = "development"
    debug: bool = True

    #: Where the SQLite corpus lives. Empty means the default inside the
    #: package (app/data/assets/maskan.db), which is right for a checkout run
    #: from source. A container points it at a mounted volume instead, so the
    #: database survives the image being rebuilt and the 100+ MB of it never
    #: enters an image layer.
    db_path: str = ""

    #: Browsers that may call this API, comma-separated. The frontend is served
    #: from a different origin than the API in every deployment shape this
    #: project has, so there is always at least one, and in production it is
    #: never the localhost default.
    cors_allow_origins: str = "http://localhost:3000"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


settings = Settings()
