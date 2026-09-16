"""Small reusable process pool with a killable deadline for each SDK call."""

import json
import logging
import multiprocessing
import subprocess
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from queue import LifoQueue
from typing import Any, Protocol

from a_stock_lab.features.trend_radar.adapters.provider_process import serve

logger = logging.getLogger(__name__)


class WorkerChannel(Protocol):
    """Common message API of POSIX Connection and Windows PipeConnection."""

    def send(self, obj: Any) -> None: ...
    def recv(self) -> Any: ...
    def poll(self, timeout: float | None = 0.0) -> bool: ...
    def close(self) -> None: ...


class ProviderWorker:
    def __init__(
        self, target: Callable[[Connection], None] = serve, max_requests: int = 250
    ) -> None:
        self.target = target
        self.max_requests = max_requests
        self.served = 0
        self.process: BaseProcess | None = None
        self.connection: WorkerChannel | None = None

    def close(self) -> None:
        self.served = 0
        process, self.process = self.process, None
        connection, self.connection = self.connection, None
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            process.close()
        if connection is not None:
            connection.close()

    def request(self, action: str, args: tuple[str, ...], timeout: float) -> Any:
        if self.served >= self.max_requests:
            self.close()  # Bound native SDK/JavaScript-engine memory growth during long scans.
        if self.process is None:
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe()
            self.connection = parent
            self.process = context.Process(target=self.target, args=(child,), daemon=True)
            try:
                self.process.start()
            except BaseException:
                self.connection.close()
                self.connection, self.process = None, None
                raise
            finally:
                child.close()
            logger.info("trend_provider_worker_started", extra={"worker_pid": self.process.pid})
        assert self.connection is not None
        try:
            self.connection.send((action, args))
            if not self.connection.poll(timeout):
                raise subprocess.TimeoutExpired(action, timeout)
            response = self.connection.recv()
            self.served += 1
        except (EOFError, OSError, subprocess.TimeoutExpired) as exc:
            self.close()  # Kill hung/crashed worker; a retry gets a fresh process and pipe.
            if isinstance(exc, EOFError):
                raise subprocess.SubprocessError("Provider worker exited before replying") from exc
            raise
        if not isinstance(response, dict):
            self.close()
            raise ValueError("Invalid provider worker response")
        if "error" in response:
            raise subprocess.CalledProcessError(1, action, output=json.dumps(response))
        return response.get("rows")


class ProviderProcessPool:
    def __init__(self, size: int, target: Callable[[Connection], None] = serve) -> None:
        self.workers = [ProviderWorker(target) for _ in range(size)]
        self.available: LifoQueue[ProviderWorker] = LifoQueue()
        for worker in self.workers:
            self.available.put(worker)

    def request(self, action: str, args: tuple[str, ...], timeout: float) -> Any:
        worker = self.available.get(timeout=timeout)
        try:
            return worker.request(action, args, timeout)
        finally:
            self.available.put(worker)

    def close(self) -> None:
        # Owner first joins its bounded collection threads, then releases SDK processes.
        for worker in self.workers:
            worker.close()
