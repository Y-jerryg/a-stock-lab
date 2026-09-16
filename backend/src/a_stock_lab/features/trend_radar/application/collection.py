"""Bounded prefetch; the caller alone checkpoints results in stable universe order."""

from collections import deque
from collections.abc import Callable, Generator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor


def collect_bounded[Item, Result](
    items: Sequence[Item], fetch: Callable[[int, Item], Result], workers: int
) -> Generator[tuple[int, Item, Future[Result]], None, None]:
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trend-fetch")
    pending: deque[tuple[int, Item, Future[Result]]] = deque()
    remaining = iter(enumerate(items, start=1))

    def submit() -> None:
        entry = next(remaining, None)
        if entry is not None:
            index, item = entry
            pending.append((index, item, executor.submit(fetch, index, item)))

    try:
        for _ in range(workers):
            submit()
        while pending:
            yield pending.popleft()
            # Only replenish after the caller has checkpointed and checked failure limits.
            submit()
    finally:
        for _, _, future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
