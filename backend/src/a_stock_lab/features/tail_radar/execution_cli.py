import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from a_stock_lab.core.config import get_settings
from a_stock_lab.core.time import as_market_timezone
from a_stock_lab.features.tail_radar.domain.errors import TailRadarError
from a_stock_lab.features.tail_radar.factory import (
    build_tail_radar_application_service,
    build_tail_radar_intraday_analysis_service,
    build_tail_radar_query_service,
    build_tail_radar_research_service,
    build_tail_radar_screening_service,
)
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data.errors import MarketDataError


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
        description="Execute or inspect explicit Tail Radar operations."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser(
        "execute",
        help="screen one already-persisted official full-market snapshot",
    )
    execute.add_argument("--snapshot-id", type=_uuid, required=True)
    analyze = commands.add_parser(
        "analyze-intraday",
        help="calculate persisted point-in-time intraday features for one candidate",
    )
    analyze.add_argument("--candidate-id", type=_uuid, required=True)
    analyze.add_argument("--analysis-as-of", type=_aware_timestamp, required=True)
    research = commands.add_parser(
        "research",
        help="run one explicit paid OpenAI web-research diagnostic for a candidate",
    )
    research.add_argument("--candidate-id", type=_uuid, required=True)
    research.add_argument("--analysis-as-of", type=_aware_timestamp, required=True)
    research.add_argument(
        "--force",
        action="store_true",
        help="explicitly bypass the normal paid-call cache and create a forced attempt",
    )
    workflow = commands.add_parser(
        "workflow",
        help="execute the complete snapshot-to-research Tail Radar workflow",
    )
    workflow.add_argument("--intended-snapshot-time", type=_aware_timestamp, required=True)
    workflow.add_argument("--analysis-as-of", type=_aware_timestamp)
    resume = commands.add_parser(
        "resume",
        help="resume an incomplete Tail Radar workflow without repeating successful stages",
    )
    resume.add_argument("--workflow-run-id", type=_uuid, required=True)
    resume.add_argument(
        "--retry-failed-research",
        action="store_true",
        help="explicitly create paid forced retries only for previously failed AI analyses",
    )
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
        if args.command == "analyze-intraday":
            analysis = build_tail_radar_intraday_analysis_service(get_settings()).execute(
                candidate_id=args.candidate_id,
                analysis_as_of=args.analysis_as_of,
            )
            _emit({"status": "success", **analysis.model_dump(mode="json")})
            return 0
        if args.command == "research":
            research = build_tail_radar_research_service(get_settings()).execute(
                candidate_id=args.candidate_id,
                analysis_as_of=args.analysis_as_of,
                force=args.force,
            )
            _emit(research.model_dump(mode="json"))
            return 0 if research.research.status.value in {"succeeded", "no_evidence"} else 1
        if args.command == "workflow":
            workflow = build_tail_radar_application_service(get_settings()).execute(
                intended_snapshot_time=args.intended_snapshot_time,
                analysis_as_of=args.analysis_as_of,
            )
            _emit(workflow.model_dump(mode="json"))
            return 0 if workflow.workflow.lifecycle.value == "succeeded" else 2
        if args.command == "resume":
            workflow = build_tail_radar_application_service(get_settings()).resume(
                workflow_run_id=args.workflow_run_id,
                retry_failed_research=args.retry_failed_research,
            )
            _emit(workflow.model_dump(mode="json"))
            return 0 if workflow.workflow.lifecycle.value == "succeeded" else 2
        result = build_tail_radar_screening_service(get_settings()).execute(
            snapshot_id=args.snapshot_id
        )
    except (TailRadarError, MarketDataError) as exc:
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
