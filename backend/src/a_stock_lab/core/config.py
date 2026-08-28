from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator
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
    openai_api_key: str | None = None
    market_data_api_key: str | None = None
    runtime_data_dir: Path = Path("../runtime")
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
