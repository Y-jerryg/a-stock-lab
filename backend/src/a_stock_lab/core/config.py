from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str | None = None
    postgres_db: str = "a_stock_lab"
    postgres_user: str = "a_stock_lab"
    postgres_password: str = "a_stock_lab"
    postgres_host_port: int = Field(default=55432, ge=1, le=65535)
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[AnyHttpUrl] = Field(default_factory=list)
    openai_api_key: SecretStr | None = None
    openai_research_model: str = "gpt-5.5-2026-04-23"
    openai_research_timeout_seconds: float = Field(default=90, gt=0, le=300)
    openai_research_max_output_tokens: int = Field(default=6_000, ge=500, le=20_000)
    openai_research_max_web_search_calls: int = Field(default=8, ge=1, le=20)
    openai_research_search_context_size: Literal["low", "medium", "high"] = "medium"
    market_data_api_key: str | None = None
    runtime_data_dir: Path = Path("../runtime")
    market_data_retry_attempts: int = Field(default=2, ge=1, le=3)
    market_data_retry_delay_seconds: float = Field(default=5.0, ge=0, le=60)
    market_snapshot_min_records: int = Field(default=4_000, ge=1)
    market_snapshot_max_duplicate_symbols: int = Field(default=0, ge=0)
    market_snapshot_max_missing_symbol_ratio: float = Field(default=0.001, ge=0, le=1)
    market_snapshot_max_invalid_price_ratio: float = Field(default=0.005, ge=0, le=1)
    market_snapshot_max_invalid_pct_change_ratio: float = Field(default=0.005, ge=0, le=1)
    market_snapshot_max_malformed_row_ratio: float = Field(default=0.01, ge=0, le=1)
    market_snapshot_max_abs_pct_change: float = Field(default=1_000.0, gt=0)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_database_url_uses_components(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def resolved_database_url(self) -> str:
        """Return an explicit override or a native-development PostgreSQL URL."""
        if self.database_url is not None:
            return self.database_url
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host="localhost",
            port=self.postgres_host_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @property
    def docs_enabled(self) -> bool:
        return self.app_env != "production"

    @property
    def normalized_cors_origins(self) -> list[str]:
        """Return browser Origin values without URL-model trailing slashes."""
        return [str(origin).rstrip("/") for origin in self.cors_origins]


@lru_cache
def get_settings() -> Settings:
    return Settings()
