"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_name: str = "Liber"
    app_env: str = "development"
    log_level: str = "INFO"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://liber:liber@localhost:5432/liber"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    summarization_model: str = "gpt-3.5-turbo"
    reasoning_model: str = "gpt-4-turbo"
    embedding_dimensions: int = 1536

    # Google Books API
    google_books_api_key: str = ""

    # Scraper
    scraper_rate_limit: float = 2.0
    scraper_max_reviews: int = 10
    scraper_timeout: int = 30

    # Agent settings
    candidate_top_n: int = 20
    explanation_top_n: int = 10
    taste_profile_cache_ttl: int = 86400  # 24 hours
    recommendation_cache_ttl: int = 3600  # 1 hour

    @property
    def sync_database_url(self) -> str:
        """Return synchronous database URL for Alembic."""
        return self.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")


settings = Settings()
