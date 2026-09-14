import pytest

from a_stock_lab.core.config import Settings
from a_stock_lab.features.tail_radar.domain.errors import TailRadarResearchConfigurationError
from a_stock_lab.features.tail_radar.factory import build_tail_radar_research_service


def test_cors_origins_are_normalized_for_exact_browser_matching() -> None:
    settings = Settings(cors_origins=["http://localhost:5173", "https://example.test/app/"])

    assert settings.normalized_cors_origins == [
        "http://localhost:5173",
        "https://example.test/app",
    ]


def test_native_database_url_uses_shared_postgres_components() -> None:
    settings = Settings(
        database_url=None,
        postgres_db="research",
        postgres_user="analyst",
        postgres_password="local_password",
        postgres_host_port=5433,
    )

    assert settings.resolved_database_url == (
        "postgresql+psycopg://analyst:local_password@localhost:5433/research"
    )


def test_explicit_database_url_takes_precedence() -> None:
    settings = Settings(database_url="postgresql+psycopg://user:pass@postgres:5432/database")

    assert settings.resolved_database_url == (
        "postgresql+psycopg://user:pass@postgres:5432/database"
    )


def test_openai_key_is_secret_and_research_requires_explicit_backend_configuration() -> None:
    settings = Settings(openai_api_key="test-secret")

    assert "test-secret" not in repr(settings)

    with pytest.raises(TailRadarResearchConfigurationError, match="OPENAI_API_KEY"):
        build_tail_radar_research_service(Settings(openai_api_key=None))
    with pytest.raises(TailRadarResearchConfigurationError, match="OPENAI_API_KEY"):
        build_tail_radar_research_service(Settings(openai_api_key="   "))


def test_on_demand_browser_research_needs_only_the_explicit_feature_flag() -> None:
    settings = Settings(
        openai_api_key=None,
        tail_radar_on_demand_research_enabled=True,
    )

    assert settings.tail_radar_on_demand_research_enabled
    assert "tail_radar_operations_token" not in Settings.model_fields
