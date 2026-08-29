import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from a_stock_lab.core.config import get_settings
from a_stock_lab.core.time import as_market_timezone, now_in_market_timezone
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.errors import MarketDataError
from a_stock_lab.shared.market_data.execution_factory import (
    build_snapshot_execution_engine,
    build_snapshot_execution_repository,
)


def _aware_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return as_market_timezone(datetime.fromisoformat(normalized))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "timestamp must be ISO 8601 with an explicit UTC offset"
        ) from exc


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a UUID") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute or inspect point-in-time full-market snapshots."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    execute_now = commands.add_parser(
        "execute-now", help="use the current Asia/Shanghai time as the intended snapshot time"
    )
    execute_now.add_argument(
        "--force", action="store_true", help="create an explicit non-official rerun"
    )
    execute_at = commands.add_parser(
        "execute-at", help="execute an explicitly identified intended snapshot slot"
    )
    execute_at.add_argument("intended_snapshot_time", type=_aware_timestamp)
    execute_at.add_argument(
        "--force", action="store_true", help="create an explicit non-official rerun"
    )
    inspect = commands.add_parser("inspect", help="inspect a persisted run and manifest")
    identifier = inspect.add_mutually_exclusive_group(required=True)
    identifier.add_argument("--run-id", type=_uuid)
    identifier.add_argument("--snapshot-id", type=_uuid)
    return parser


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "inspect":
        try:
            return _inspect(run_id=args.run_id, snapshot_id=args.snapshot_id)
        except MarketDataError as exc:
            _emit(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            return 1

    intended_snapshot_time = (
        now_in_market_timezone() if args.command == "execute-now" else args.intended_snapshot_time
    )
    try:
        result = build_snapshot_execution_engine(get_settings()).execute(
            intended_snapshot_time=intended_snapshot_time,
            force=args.force,
        )
    except MarketDataError as exc:
        _emit(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        return 1
    _emit({"status": result.run.status.value, **result.model_dump(mode="json")})
    return 0 if result.run.status is RunStatus.SUCCEEDED else 1


def _inspect(*, run_id: UUID | None, snapshot_id: UUID | None) -> int:
    repository = build_snapshot_execution_repository()
    if snapshot_id is not None:
        manifest = repository.get_manifest(snapshot_id)
        run = None if manifest is None else repository.get_run(manifest.run_id)
    else:
        if run_id is None:
            raise AssertionError("an inspection identifier is required")
        run = repository.get_run(run_id)
        manifest = None if run is None else repository.get_manifest_for_run(run_id)
    if run is None:
        _emit({"status": "not_found"})
        return 1
    _emit(
        {
            "status": "success",
            "run": run.model_dump(mode="json"),
            "manifest": None if manifest is None else manifest.model_dump(mode="json"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
