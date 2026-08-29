import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from a_stock_lab.core.config import get_settings
from a_stock_lab.features.tail_radar.domain.errors import TailRadarError
from a_stock_lab.features.tail_radar.factory import (
    build_tail_radar_query_service,
    build_tail_radar_screening_service,
)
from a_stock_lab.shared.execution.models import RunStatus


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a UUID") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute or inspect deterministic Tail Radar screening."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser(
        "execute",
        help="screen one already-persisted official full-market snapshot",
    )
    execute.add_argument("--snapshot-id", type=_uuid, required=True)
    inspect = commands.add_parser("inspect", help="inspect one persisted Tail Radar run")
    inspect.add_argument("--run-id", type=_uuid, required=True)
    return parser


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            run = build_tail_radar_query_service().get_run(args.run_id)
            if run is None:
                _emit({"status": "not_found"})
                return 1
            _emit({"status": "success", "run": run.model_dump(mode="json")})
            return 0
        result = build_tail_radar_screening_service(get_settings()).execute(
            snapshot_id=args.snapshot_id
        )
    except TailRadarError as exc:
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


if __name__ == "__main__":
    raise SystemExit(main())
