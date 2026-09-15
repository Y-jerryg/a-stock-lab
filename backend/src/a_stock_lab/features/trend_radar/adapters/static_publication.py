import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from a_stock_lab.features.trend_radar.application.contracts import LocalRepository
from a_stock_lab.features.trend_radar.domain.models import (
    COMPLETED_STATUSES,
    TrendError,
    candidate_order,
)
from a_stock_lab.features.trend_radar.domain.publication import (
    PublicIndex,
    PublicResults,
    PublicRun,
    PublicRunDetails,
    PublicStockDetail,
)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".trend-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # The exporter and Nginx run under different users. Public JSON must be readable
        # by the static server; mkstemp otherwise leaves it owner-only (0600).
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class StaticResultPublisher:
    def __init__(self, source: LocalRepository, directory: Path) -> None:
        self.source, self.directory = source, directory

    def publish(self) -> None:
        runs = sorted(
            self.source.public_runs(), key=lambda run: (run.started_at, str(run.id)), reverse=True
        )
        public = [PublicRun.from_run(run) for run in runs]
        successful = [run for run in runs if run.status in COMPLETED_STATUSES]
        try:
            for run in successful:
                results = self.source.public_results(run.id)
                if (
                    len(results) != run.candidate_count
                    or len({item.symbol for item in results}) != len(results)
                    or sum(item.is_strong_volume_contraction for item in results)
                    != run.strong_contraction_count
                ):
                    raise TrendError("publication_result_mismatch")
                results.sort(
                    key=lambda item: candidate_order(
                        item, int(str(run.configuration_snapshot["top_n"]))
                    )
                )
                inputs = self.source.candidate_inputs(run.id)
                details = PublicRunDetails(
                    run=PublicRun.from_run(run),
                    details=[
                        PublicStockDetail(candidate=row, bars=inputs.get(row.symbol, []))
                        for row in results
                    ],
                )
                detail_content = details.model_dump_json()
                detail_target = self.directory / "details" / f"{run.id}.json"
                if (
                    not detail_target.exists()
                    or detail_target.read_text(encoding="utf-8") != detail_content
                ):
                    atomic_write(detail_target, detail_content)
                else:
                    detail_target.chmod(0o644)
                content = PublicResults(run_id=run.id, results=results).model_dump_json()
                target = self.directory / "runs" / f"{run.id}.json"
                if not target.exists() or target.read_text(encoding="utf-8") != content:
                    atomic_write(target, content)
                else:
                    target.chmod(0o644)
            index = PublicIndex(
                generated_at=datetime.now(UTC),
                attempts=public,
                latest=PublicRun.from_run(successful[0]) if successful else None,
            )
            # Results are durable before the index switches to a new successful run.
            atomic_write(self.directory / "index.json", index.model_dump_json())
        except OSError as exc:
            raise TrendError("publication_error") from exc

    def bundle(self, destination: Path) -> None:
        self.publish()
        index_path = self.directory / "index.json"
        index = PublicIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".zip")
        os.close(descriptor)
        try:
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
                archive.write(index_path, "index.json")
                for run in index.attempts:
                    if run.status in COMPLETED_STATUSES:
                        relative = f"runs/{run.id}.json"
                        archive.write(self.directory / relative, relative)
                        detail_relative = f"details/{run.id}.json"
                        archive.write(self.directory / detail_relative, detail_relative)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
