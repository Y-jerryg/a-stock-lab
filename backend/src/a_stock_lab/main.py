from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from a_stock_lab import __version__
from a_stock_lab.api.errors import register_exception_handlers
from a_stock_lab.api.internal.router import internal_api_router
from a_stock_lab.api.v1.router import api_v1_router
from a_stock_lab.core.config import get_settings
from a_stock_lab.core.logging import configure_logging, get_logger
from a_stock_lab.core.middleware import RequestContextMiddleware

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("application_started", extra={"feature": "system"})
    yield
    logger.info("application_stopped", extra={"feature": "system"})


def create_app() -> FastAPI:
    app = FastAPI(
        title="A-Stock Lab API",
        version=__version__,
        description="Backend API for the A-Stock Lab research platform.",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    if settings.normalized_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.normalized_cors_origins,
            allow_credentials=False,
            allow_methods=[
                "GET",
                *(["POST"] if settings.tail_radar_on_demand_research_enabled else []),
            ],
            allow_headers=[
                "Accept",
                "Content-Type",
                "X-Request-ID",
                *(["X-OpenAI-API-Key"] if settings.tail_radar_on_demand_research_enabled else []),
            ],
        )
    register_exception_handlers(app)
    app.include_router(api_v1_router, prefix="/api/v1")
    app.include_router(internal_api_router, prefix="/api/internal/v1")
    return app


app = create_app()
