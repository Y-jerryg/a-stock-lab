import json
import os
from pathlib import Path
from uuid import uuid4

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from a_stock_lab.shared.market_data.errors import SnapshotPersistenceError
from a_stock_lab.shared.market_data.models import FullMarketSnapshot

_MANIFEST_METADATA_KEY = b"a_stock_lab.snapshot_manifest"
_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("exchange", pa.string()),
        pa.field("name", pa.string()),
        pa.field("price", pa.float64()),
        pa.field("pct_change", pa.float64()),
        pa.field("absolute_change", pa.float64()),
        pa.field("open", pa.float64()),
        pa.field("high", pa.float64()),
        pa.field("low", pa.float64()),
        pa.field("previous_close", pa.float64()),
        pa.field("volume", pa.float64()),
        pa.field("amount", pa.float64()),
        pa.field("amplitude", pa.float64()),
        pa.field("volume_ratio", pa.float64()),
        pa.field("turnover_rate", pa.float64()),
        pa.field("pe_dynamic", pa.float64()),
        pa.field("pb", pa.float64()),
        pa.field("total_market_cap", pa.float64()),
        pa.field("float_market_cap", pa.float64()),
        pa.field("provider", pa.string(), nullable=False),
        pa.field("provider_timestamp", pa.timestamp("us", tz="Asia/Shanghai")),
        pa.field("fetched_at", pa.timestamp("us", tz="Asia/Shanghai"), nullable=False),
    ]
)


class ParquetMarketSnapshotWriter:
    """Persist validated snapshots atomically, with the manifest in Parquet metadata."""

    def __init__(self, runtime_data_dir: Path) -> None:
        self._runtime_data_dir = runtime_data_dir

    def write(self, snapshot: FullMarketSnapshot) -> Path:
        date_partition = snapshot.manifest.request_finished_at.strftime("%Y-%m-%d")
        target_directory = self._runtime_data_dir / "market-data" / date_partition
        target = target_directory / f"full-market-{snapshot.manifest.snapshot_id}.parquet"
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")

        try:
            target_directory.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(f"snapshot already exists: {target}")

            rows: list[dict[str, object]] = []
            for record in snapshot.records:
                row = record.model_dump(mode="python")
                row["exchange"] = record.exchange.value if record.exchange is not None else None
                rows.append(row)

            manifest_json = json.dumps(
                snapshot.manifest.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            schema = _PARQUET_SCHEMA.with_metadata(
                {_MANIFEST_METADATA_KEY: manifest_json.encode("utf-8")}
            )
            table = pa.Table.from_pylist(rows, schema=schema)
            pq.write_table(table, temporary, compression="zstd", version="2.6")
            os.replace(temporary, target)
        except (OSError, pa.ArrowException) as exc:
            raise SnapshotPersistenceError(target=target) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                raise SnapshotPersistenceError(target=target) from exc
        return target
