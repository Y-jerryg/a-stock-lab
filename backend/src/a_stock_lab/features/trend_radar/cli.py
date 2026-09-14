import argparse
import json
import logging
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text

from a_stock_lab.core.config import get_settings
from a_stock_lab.core.logging import configure_logging
from a_stock_lab.features.trend_radar.adapters.static_publication import StaticResultPublisher
from a_stock_lab.features.trend_radar.application.worker import TrendWorker
from a_stock_lab.features.trend_radar.domain.models import COMPLETED_STATUSES, TrendError
from a_stock_lab.features.trend_radar.factory import (
    create_heartbeat,
    create_repository,
    create_service,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="trend-radar")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="Start a scan locally and export public results")
    commands.add_parser("worker", help="Run the optional local daily scheduler")
    commands.add_parser("worker-once", help="Perform one scheduler iteration")
    inspect = commands.add_parser("inspect", help="Inspect a local scan attempt")
    inspect.add_argument("--run-id", type=UUID)
    commands.add_parser("health", help="Read-only local database check")
    commands.add_parser("worker-health", help="Read-only local worker liveness check")
    export = commands.add_parser(
        "export", help="Re-export stored results without fetching market data"
    )
    export.add_argument("--output-dir", type=Path)
    bundle = commands.add_parser(
        "bundle", help="Package only public result files for website deployment"
    )
    bundle.add_argument("--output", type=Path)
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    try:
        if args.command == "inspect":
            sys.stdout.write(
                json.dumps(create_repository().inspect(args.run_id), default=str) + "\n"
            )
        elif args.command == "health":
            with create_engine(get_settings().resolved_database_url).connect() as connection:
                connection.execute(text("SELECT 1 FROM trend_schedule_claims LIMIT 1"))
            sys.stdout.write('{"database":"ready"}\n')
        elif args.command == "worker-health":
            healthy = create_heartbeat().healthy(datetime.now(UTC))
            sys.stdout.write(json.dumps({"healthy": healthy}) + "\n")
            if not healthy:
                raise SystemExit(1)
        elif args.command in {"export", "bundle"}:
            repository = create_repository()
            directory = get_settings().runtime_data_dir / "public/trend-radar"
            if args.command == "export" and args.output_dir:
                directory = args.output_dir
            publisher = StaticResultPublisher(repository, directory)
            with repository.lock():
                if args.command == "bundle":
                    output = (
                        args.output or get_settings().runtime_data_dir / "trend-radar-public.zip"
                    )
                    publisher.bundle(output)
                else:
                    publisher.publish()
                    output = directory
            sys.stdout.write(json.dumps({"output": str(output)}) + "\n")
        elif args.command == "scan":
            run = create_service().scan("cli")
            sys.stdout.write(run.model_dump_json() + "\n" if run else '{"status":"busy"}\n')
            if run is None or run.status not in COMPLETED_STATUSES:
                raise SystemExit(1)
        else:
            worker = TrendWorker(create_service(), create_heartbeat())
            if args.command == "worker-once":
                worker.tick()
            else:
                signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
                signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
                worker.run()
    except Exception as exc:
        code = exc.code if isinstance(exc, TrendError) else "configuration_or_dependency_error"
        logging.getLogger(__name__).exception(
            "trend_command_failed",
            extra={
                "error_code": code,
                "exception_type": type(exc).__name__,
            },
        )
        sys.stderr.write(json.dumps({"error": code}) + "\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
