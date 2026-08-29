import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from a_stock_lab.core.config import get_settings
from a_stock_lab.core.time import now_in_market_timezone
from a_stock_lab.shared.market_data.adapters.factory import (
    build_market_data_provider,
    build_snapshot_quality_thresholds,
)
from a_stock_lab.shared.market_data.adapters.parquet import ParquetMarketSnapshotWriter
from a_stock_lab.shared.market_data.errors import (
    MarketDataQualityError,
    ProviderError,
    SnapshotPersistenceError,
)
from a_stock_lab.shared.market_data.service import FullMarketSnapshotService

_MINIMUM_REPEAT_INTERVAL_SECONDS = 30.0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manually fetch and validate a live full-market snapshot.",
    )
    parser.add_argument(
        "--persist", action="store_true", help="write accepted snapshots to Parquet"
    )
    parser.add_argument("--samples", type=_positive_int, default=5, help="normalized rows to print")
    parser.add_argument(
        "--repeat", type=_positive_int, default=1, help="number of live observations"
    )
    parser.add_argument(
        "--interval-seconds",
        type=_non_negative_float,
        default=60.0,
        help="delay between repeated observations (minimum 30 seconds)",
    )
    return parser


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.repeat > 1 and args.interval_seconds < _MINIMUM_REPEAT_INTERVAL_SECONDS:
        parser.error(
            f"repeated live calls require at least {_MINIMUM_REPEAT_INTERVAL_SECONDS:g} seconds "
            "between observations"
        )

    settings = get_settings()
    provider = build_market_data_provider(settings)
    service = FullMarketSnapshotService(
        provider=provider,
        thresholds=build_snapshot_quality_thresholds(settings),
    )
    writer = ParquetMarketSnapshotWriter(Path(settings.runtime_data_dir)) if args.persist else None
    had_failure = False

    for observation in range(1, args.repeat + 1):
        outer_started_at = now_in_market_timezone()
        timer_started_at = time.perf_counter()
        try:
            snapshot = service.fetch()
            persisted = writer.write(snapshot) if writer is not None else None
            _emit(
                {
                    "observation": observation,
                    "status": "success",
                    "snapshot_id": str(snapshot.manifest.snapshot_id),
                    "provider": snapshot.manifest.provider,
                    "actual_fetch_started_at": (
                        snapshot.manifest.actual_fetch_started_at.isoformat()
                    ),
                    "actual_fetch_finished_at": (
                        snapshot.manifest.actual_fetch_finished_at.isoformat()
                    ),
                    "latency_ms": snapshot.manifest.latency_ms,
                    "record_count": snapshot.manifest.record_count,
                    "quality_report": snapshot.manifest.quality_report.model_dump(mode="json"),
                    "sample_records": [
                        record.model_dump(mode="json")
                        for record in snapshot.records[: args.samples]
                    ],
                    "persisted_to": (
                        str(Path(settings.runtime_data_dir) / persisted.storage_key)
                        if persisted is not None
                        else None
                    ),
                    "checksum_sha256": (
                        persisted.checksum_sha256 if persisted is not None else None
                    ),
                }
            )
        except MarketDataQualityError as exc:
            had_failure = True
            _emit(
                {
                    "observation": observation,
                    "status": "quality_failed",
                    "provider": exc.provider,
                    "actual_fetch_started_at": exc.actual_fetch_started_at.isoformat(),
                    "actual_fetch_finished_at": exc.actual_fetch_finished_at.isoformat(),
                    "latency_ms": exc.latency_ms,
                    "record_count": exc.report.normalized_record_count,
                    "quality_report": exc.report.model_dump(mode="json"),
                }
            )
        except ProviderError as exc:
            had_failure = True
            finished_at = now_in_market_timezone()
            _emit(
                {
                    "observation": observation,
                    "status": "provider_failed",
                    "provider": exc.provider,
                    "actual_fetch_started_at": outer_started_at.isoformat(),
                    "actual_fetch_finished_at": finished_at.isoformat(),
                    "latency_ms": round((time.perf_counter() - timer_started_at) * 1_000, 3),
                    "record_count": 0,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        except SnapshotPersistenceError as exc:
            had_failure = True
            _emit(
                {
                    "observation": observation,
                    "status": "persistence_failed",
                    "snapshot_id": str(snapshot.manifest.snapshot_id),
                    "provider": snapshot.manifest.provider,
                    "actual_fetch_started_at": (
                        snapshot.manifest.actual_fetch_started_at.isoformat()
                    ),
                    "actual_fetch_finished_at": (
                        snapshot.manifest.actual_fetch_finished_at.isoformat()
                    ),
                    "latency_ms": snapshot.manifest.latency_ms,
                    "record_count": snapshot.manifest.record_count,
                    "quality_report": snapshot.manifest.quality_report.model_dump(mode="json"),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

        if observation < args.repeat:
            time.sleep(args.interval_seconds)

    return 1 if had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
