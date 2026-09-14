"""Install only the allowlisted public JSON bundle into a static website build."""

import argparse
import json
import math
from datetime import date, datetime
from pathlib import Path
from uuid import UUID
from zipfile import ZipFile


def unpack(source: Path, destination: Path) -> None:
    with ZipFile(source) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or len(names) > 203:
            raise ValueError("Duplicate or too many bundle entries")
        if sum(entry.file_size for entry in entries) > 50 * 1024 * 1024:
            raise ValueError("Uncompressed bundle too large")
        index = json.loads(archive.read("index.json"))
        if index.get("schema_version") not in {1, 2} or not isinstance(index.get("attempts"), list):
            raise ValueError("Unsupported publication schema")
        detail_version = index.get("detail_schema_version")
        if detail_version not in {None, 1}:
            raise ValueError("Unsupported detail schema")
        allowed = {"index.json"}
        success = {}
        for run in index["attempts"]:
            run_id = str(UUID(run["id"]))
            if run["id"] != run_id or run.get("status") not in {
                "running",
                "failed",
                "success",
                "completed_with_warnings",
            }:
                raise ValueError("Invalid run")
            if run["status"] in {"success", "completed_with_warnings"}:
                if run_id in success:
                    raise ValueError("Duplicate successful run")
                success[run_id] = run
                name = f"runs/{run_id}.json"
                allowed.add(name)
                result = json.loads(archive.read(name))
                if result.get("schema_version") != 1 or result.get("run_id") != run_id:
                    raise ValueError("Mismatched result file")
                rows = result.get("results")
                if not isinstance(rows, list) or len(rows) != run["payload"]["candidate_count"]:
                    raise ValueError("Mismatched candidate count")
                if len({row["symbol"] for row in rows}) != len(rows):
                    raise ValueError("Duplicate symbols")
                if detail_version == 1:
                    detail_name = f"details/{run_id}.json"
                    allowed.add(detail_name)
                    detail = json.loads(archive.read(detail_name))
                    validate_details(detail, run, rows)
        latest = index.get("latest")
        if (latest is None and success) or (
            latest is not None and success.get(latest["id"]) != latest
        ):
            raise ValueError("Invalid latest successful run")
        if set(names) != allowed:
            raise ValueError("Bundle contains unexpected files")
        # All validation finishes before writing. UUID paths are constructed here, never extracted.
        for name in sorted(allowed):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))


def validate_details(detail: dict, run: dict, rows: list) -> None:
    if (
        detail.get("schema_version") != 1
        or detail.get("run") != run
        or detail.get("volume_unit") != "lot"
        or detail.get("amount_unit") != "CNY"
    ):
        raise ValueError("Mismatched detail file")
    items = detail.get("details")
    if not isinstance(items, list) or [item.get("candidate") for item in items] != rows:
        raise ValueError("Mismatched detail candidates")
    bar_fields = {
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adjustment_type",
        "source",
        "fetched_at",
    }
    for item in items:
        bars = item.get("bars")
        if not isinstance(bars, list):
            raise ValueError("Invalid detail bars")
        previous = ""
        for bar in bars:
            if (
                set(bar) != bar_fields
                or bar["symbol"] != item["candidate"]["symbol"]
                or bar["adjustment_type"] != "qfq"
                or not previous < bar["trade_date"] <= run["trade_date"]
                or datetime.fromisoformat(bar["fetched_at"].replace("Z", "+00:00"))
                > datetime.fromisoformat(run["payload"]["data_as_of"].replace("Z", "+00:00"))
                or any(
                    not isinstance(bar[key], (int, float))
                    or isinstance(bar[key], bool)
                    or not math.isfinite(bar[key])
                    or bar[key] < 0
                    for key in ("open", "high", "low", "close", "volume", "amount")
                )
            ):
                raise ValueError("Invalid detail bar boundary or values")
            if (
                date.fromisoformat(bar["trade_date"]).isoformat() != bar["trade_date"]
                or datetime.fromisoformat(bar["fetched_at"].replace("Z", "+00:00")).tzinfo is None
                or min(bar[key] for key in ("open", "high", "low", "close")) <= 0
                or bar["low"] > min(bar["open"], bar["close"])
                or bar["high"] < max(bar["open"], bar["close"])
                or not isinstance(bar["source"], str)
                or not bar["source"]
            ):
                raise ValueError("Invalid detail bar boundary or values")
            previous = bar["trade_date"]
        if bars and previous != item["candidate"]["trend_end_date"]:
            raise ValueError("Mismatched detail trend end")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    unpack(args.source, args.destination)
