"""Context shared by scan orchestration and provider attempt logs."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_stock_context: ContextVar[dict[str, object] | None] = ContextVar(
    "trend_stock_context", default=None
)


def stock_context() -> dict[str, object]:
    return _stock_context.get() or {}


@contextmanager
def scanning_stock(**fields: object) -> Iterator[None]:
    token = _stock_context.set(fields)
    try:
        yield
    finally:
        _stock_context.reset(token)
