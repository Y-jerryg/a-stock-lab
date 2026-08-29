from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from a_stock_lab.core.time import as_market_timezone, now_in_market_timezone
from a_stock_lab.features.tail_radar.application.contracts import (
    MarketSnapshotArtifactReader,
    TailRadarRepository,
)
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateCreate,
    TailRadarCandidatePayload,
    TailRadarExecutionDisposition,
    TailRadarScreeningResult,
)
from a_stock_lab.features.tail_radar.domain.errors import (
    TailRadarCommitUncertainError,
    TailRadarPersistenceError,
    TailRadarSnapshotIntegrityError,
    TailRadarSourceSnapshotNotFoundError,
)
from a_stock_lab.features.tail_radar.domain.screening import (
    TailRadarDecisionOutcome,
    TailRadarScreeningInput,
    TailRadarScreeningRule,
    TailRadarSnapshotEvidence,
)
from a_stock_lab.shared.market_data.errors import SnapshotArtifactIntegrityError
from a_stock_lab.shared.market_data.models import FullMarketSnapshot
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest


class TailRadarScreeningService:
    """Screen exactly one persisted official point-in-time full-market snapshot."""

    def __init__(
        self,
        *,
        rule: TailRadarScreeningRule,
        reader: MarketSnapshotArtifactReader,
        repository: TailRadarRepository,
        clock: Callable[[], datetime] = now_in_market_timezone,
    ) -> None:
        self._rule = rule
        self._reader = reader
        self._repository = repository
        self._clock = clock

    def execute(self, *, snapshot_id: UUID) -> TailRadarScreeningResult:
        source = self._repository.get_official_snapshot(snapshot_id)
        if source is None:
            raise TailRadarSourceSnapshotNotFoundError(
                "Tail Radar requires a successful official market snapshot"
            )
        started_at = as_market_timezone(self._clock())
        if started_at < source.persisted_at:
            raise TailRadarSnapshotIntegrityError(
                "Tail Radar execution cannot precede source snapshot persistence"
            )
        claim = self._repository.claim_run(
            snapshot=source,
            screening_rule_version=self._rule.version,
            rule_configuration=self._rule.configuration,
            started_at=started_at,
        )
        if not claim.created:
            return TailRadarScreeningResult(
                disposition=TailRadarExecutionDisposition.IDEMPOTENT_REPLAY,
                run=claim.run,
            )

        try:
            try:
                snapshot = self._reader.read(source)
            except SnapshotArtifactIntegrityError as exc:
                raise TailRadarSnapshotIntegrityError(
                    "registered market snapshot artifact failed integrity validation"
                ) from exc
            _validate_snapshot_artifact(snapshot, source)
            evidence = _snapshot_evidence(source)
            candidates: list[TailRadarCandidateCreate] = []
            invalid_record_count = 0
            for record in snapshot.records:
                decision = self._rule.evaluate(
                    TailRadarScreeningInput(record=record, snapshot_evidence=evidence)
                )
                if decision.outcome is TailRadarDecisionOutcome.INVALID:
                    invalid_record_count += 1
                elif decision.included:
                    candidates.append(
                        TailRadarCandidateCreate(
                            candidate_id=uuid4(),
                            run_id=claim.run.run_id,
                            snapshot_id=source.snapshot_id,
                            symbol=record.symbol,
                            trade_date=source.trade_date,
                            as_of=evidence.as_of,
                            payload=TailRadarCandidatePayload(
                                screening_rule_version=self._rule.version,
                                rule_configuration=self._rule.configuration,
                                snapshot_evidence=evidence,
                                snapshot_record=record,
                                decision=decision,
                            ),
                        )
                    )
            completed = self._repository.complete_run(
                run_id=claim.run.run_id,
                candidates=candidates,
                evaluated_record_count=len(snapshot.records),
                invalid_record_count=invalid_record_count,
                finished_at=as_market_timezone(self._clock()),
            )
        except TailRadarCommitUncertainError:
            raise
        except Exception as exc:
            try:
                self._repository.fail_run(
                    run_id=claim.run.run_id,
                    finished_at=as_market_timezone(self._clock()),
                    error_code=type(exc).__name__,
                )
            except TailRadarPersistenceError as recording_error:
                raise recording_error from exc
            raise
        return TailRadarScreeningResult(
            disposition=TailRadarExecutionDisposition.CREATED,
            run=completed,
        )


def _snapshot_evidence(manifest: PersistedSnapshotManifest) -> TailRadarSnapshotEvidence:
    return TailRadarSnapshotEvidence(
        snapshot_id=manifest.snapshot_id,
        snapshot_run_id=manifest.run_id,
        trade_date=manifest.trade_date,
        intended_snapshot_time=manifest.intended_snapshot_time,
        actual_fetch_started_at=manifest.actual_fetch_started_at,
        actual_fetch_finished_at=manifest.actual_fetch_finished_at,
        provider=manifest.provider,
        provider_timestamp=manifest.provider_timestamp,
        checksum_sha256=manifest.checksum_sha256,
        snapshot_schema_version=manifest.schema_version,
    )


def _validate_snapshot_artifact(
    snapshot: FullMarketSnapshot,
    persisted: PersistedSnapshotManifest,
) -> None:
    embedded = snapshot.manifest
    mismatched = (
        embedded.snapshot_id != persisted.snapshot_id
        or embedded.provider != persisted.provider
        or embedded.provider_version != persisted.provider_version
        or embedded.provider_timestamp != persisted.provider_timestamp
        or embedded.actual_fetch_started_at != persisted.actual_fetch_started_at
        or embedded.actual_fetch_finished_at != persisted.actual_fetch_finished_at
        or embedded.record_count != persisted.row_count
        or embedded.schema_version != persisted.schema_version
        or embedded.provider_metadata != persisted.provider_metadata
        or embedded.quality_report != persisted.quality_report
    )
    if mismatched:
        raise TailRadarSnapshotIntegrityError(
            "snapshot artifact does not match its registered PostgreSQL manifest"
        )
