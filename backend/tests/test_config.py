from a_stock_lab.core.config import Settings


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
