FROM ghcr.io/astral-sh/uv:0.12.7 AS uv

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=uv /uv /uvx /bin/

FROM base AS dependencies
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev

FROM base AS development
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN uv sync --locked
EXPOSE 8000
CMD ["uvicorn", "a_stock_lab.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS runtime
COPY --from=dependencies /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/runtime && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "a_stock_lab.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

