import json
import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import ValidationError

from a_stock_lab.core.logging import get_logger
from a_stock_lab.shared.market_data.errors import (
    SnapshotArtifactIntegrityError,
    SnapshotPersistenceError,
)
from a_stock_lab.shared.market_data.models import (
    FullMarketSnapshot,
    MarketSnapshotRecord,
    SnapshotManifest,
)
from a_stock_lab.shared.market_data.persistence_schemas import (
    PersistedSnapshotManifest,
    SnapshotStorageResult,
)

SNAPSHOT_MANIFEST_METADATA_KEY = b"a_stock_lab.snapshot_manifest"
logger = get_logger(__name__)
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

    def write(self, snapshot: FullMarketSnapshot) -> SnapshotStorageResult:
        date_partition = snapshot.manifest.actual_fetch_finished_at.strftime("%Y-%m-%d")
        target_directory = self._runtime_data_dir / "market-data" / date_partition
        target = target_directory / f"full-market-{snapshot.manifest.snapshot_id}.parquet"
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")

        published = False
        try:
            target_directory.mkdir(parents=True, exist_ok=True)

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
                {SNAPSHOT_MANIFEST_METADATA_KEY: manifest_json.encode("utf-8")}
            )
            table = pa.Table.from_pylist(rows, schema=schema)
            pq.write_table(table, temporary, compression="zstd", version="2.6")
            checksum = _sha256_file(temporary)
            size_bytes = temporary.stat().st_size
            os.link(temporary, target)
            published = True
        except (OSError, pa.ArrowException) as exc:
            raise SnapshotPersistenceError(target=target) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                if not published:
                    raise SnapshotPersistenceError(target=target) from exc
                logger.warning(
                    "snapshot_temporary_cleanup_failed",
                    extra={"temporary_path": str(temporary), "target_path": str(target)},
                )
        return SnapshotStorageResult(
            storage_key=target.relative_to(self._runtime_data_dir).as_posix(),
            checksum_sha256=checksum,
            size_bytes=size_bytes,
        )

    def delete(self, storage_key: str) -> None:
        root = self._runtime_data_dir.resolve()
        target = (root / storage_key).resolve()
        if not target.is_relative_to(root):
            raise SnapshotPersistenceError(target=target)
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise SnapshotPersistenceError(target=target) from exc


class ParquetMarketSnapshotReader:
    """Read and verify a normalized snapshot through its registered immutable manifest."""

    def __init__(self, runtime_data_dir: Path) -> None:
        self._runtime_data_dir = runtime_data_dir

    def read(self, manifest: PersistedSnapshotManifest) -> FullMarketSnapshot:
        root = self._runtime_data_dir.resolve()
        target = (root / manifest.storage_key).resolve()
        if not target.is_relative_to(root):
            raise SnapshotArtifactIntegrityError("snapshot storage key escaped the runtime root")
        try:
            if _sha256_readonly(target) != manifest.checksum_sha256:
                raise SnapshotArtifactIntegrityError("snapshot checksum did not match its manifest")
            table = pq.read_table(target, schema=_PARQUET_SCHEMA)
            metadata = pq.read_metadata(target).metadata or {}
            manifest_json = metadata.get(SNAPSHOT_MANIFEST_METADATA_KEY)
            if manifest_json is None:
                raise SnapshotArtifactIntegrityError("snapshot artifact has no embedded manifest")
            embedded = SnapshotManifest.model_validate_json(manifest_json)
            records = tuple(MarketSnapshotRecord.model_validate(row) for row in table.to_pylist())
            snapshot = FullMarketSnapshot(manifest=embedded, records=records)
        except SnapshotArtifactIntegrityError:
            raise
        except (OSError, pa.ArrowException, ValidationError, ValueError) as exc:
            raise SnapshotArtifactIntegrityError(
                "snapshot artifact could not be decoded safely"
            ) from exc
        if snapshot.manifest.snapshot_id != manifest.snapshot_id:
            raise SnapshotArtifactIntegrityError(
                "snapshot artifact identifier did not match its manifest"
            )
        return snapshot


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb+") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        os.fsync(stream.fileno())
    return digest.hexdigest()


def _sha256_readonly(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
