from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from a_stock_lab.api.v1.schemas.health import HealthResponse
from a_stock_lab.api.v1.services.health import HealthService, get_health_service
from a_stock_lab.core.time import now_in_market_timezone
from a_stock_lab.main import create_app


class StubHealthService(HealthService):
    def __init__(self) -> None:
        pass

    def check(self) -> HealthResponse:
        return HealthResponse.healthy(version="test", generated_at=now_in_market_timezone())


@pytest.fixture
def app() -> Iterator[FastAPI]:
    application = create_app()
    application.dependency_overrides[get_health_service] = StubHealthService
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
