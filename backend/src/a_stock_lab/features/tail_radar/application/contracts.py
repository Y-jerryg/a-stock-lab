from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from a_stock_lab.features.tail_radar.application.intraday_models import (
    TailRadarIntradayAnalysisCreate,
    TailRadarIntradayAnalysisData,
)
from a_stock_lab.features.tail_radar.application.models import (
    TailRadarCandidateCreate,
    TailRadarCandidateData,
    TailRadarCandidatePage,
    TailRadarRunClaim,
    TailRadarRunData,
    TailRadarRunPage,
)
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TailRadarCandidateStageStatus,
    TailRadarWorkflowCandidateState,
    TailRadarWorkflowClaim,
    TailRadarWorkflowData,
    TailRadarWorkflowLifecycle,
)
from a_stock_lab.features.tail_radar.application.research_models import (
    ResearchProviderRequest,
    ResearchProviderResult,
    TailRadarResearchClaimRequest,
    TailRadarResearchClaimResult,
    TailRadarResearchCompletion,
    TailRadarResearchData,
)
from a_stock_lab.features.tail_radar.domain.screening import TailRadarScreeningConfiguration
from a_stock_lab.shared.market_data.models import FullMarketSnapshot
from a_stock_lab.shared.market_data.persistence_schemas import PersistedSnapshotManifest


class MarketSnapshotArtifactReader(Protocol):
    def read(self, manifest: PersistedSnapshotManifest) -> FullMarketSnapshot: ...


class TailRadarResearchProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    def research(self, request: ResearchProviderRequest) -> ResearchProviderResult: ...


class TailRadarRepository(Protocol):
    def get_official_snapshot(self, snapshot_id: UUID) -> PersistedSnapshotManifest | None: ...

    def claim_run(
        self,
        *,
        snapshot: PersistedSnapshotManifest,
        screening_rule_version: str,
        rule_configuration: TailRadarScreeningConfiguration,
        started_at: datetime,
    ) -> TailRadarRunClaim: ...

    def complete_run(
        self,
        *,
        run_id: UUID,
        candidates: Sequence[TailRadarCandidateCreate],
        evaluated_record_count: int,
        invalid_record_count: int,
        finished_at: datetime,
    ) -> TailRadarRunData: ...

    def fail_run(
        self,
        *,
        run_id: UUID,
        finished_at: datetime,
        error_code: str,
    ) -> TailRadarRunData: ...

    def get_latest_run(self) -> TailRadarRunData | None: ...

    def list_runs(self, *, offset: int, limit: int) -> TailRadarRunPage: ...

    def get_run(self, run_id: UUID) -> TailRadarRunData | None: ...

    def list_candidates(
        self, *, run_id: UUID, offset: int, limit: int
    ) -> TailRadarCandidatePage: ...

    def get_candidate(self, candidate_id: UUID) -> TailRadarCandidateData | None: ...

    def get_intraday_analysis(
        self,
        *,
        candidate_id: UUID,
        analysis_as_of: datetime,
        calculation_version: str,
    ) -> TailRadarIntradayAnalysisData | None: ...

    def get_latest_intraday_analysis(
        self, candidate_id: UUID
    ) -> TailRadarIntradayAnalysisData | None: ...

    def get_latest_intraday_analyses(
        self, candidate_ids: Sequence[UUID]
    ) -> dict[UUID, TailRadarIntradayAnalysisData]: ...

    def get_intraday_analysis_at_or_before(
        self, *, candidate_id: UUID, analysis_as_of: datetime
    ) -> TailRadarIntradayAnalysisData | None: ...

    def save_intraday_analysis(
        self, analysis: TailRadarIntradayAnalysisCreate
    ) -> tuple[TailRadarIntradayAnalysisData, bool]: ...

    def claim_research(
        self, request: TailRadarResearchClaimRequest
    ) -> TailRadarResearchClaimResult: ...

    def complete_research(
        self, completion: TailRadarResearchCompletion
    ) -> TailRadarResearchData: ...

    def fail_research(
        self, *, research_id: UUID, finished_at: datetime, error_code: str
    ) -> TailRadarResearchData: ...

    def get_latest_research(self, candidate_id: UUID) -> TailRadarResearchData | None: ...


class TailRadarWorkflowRepository(Protocol):
    def claim_workflow(
        self,
        *,
        intended_snapshot_time: datetime,
        requested_analysis_as_of: datetime | None,
        workflow_version: str,
        started_at: datetime,
    ) -> TailRadarWorkflowClaim: ...

    def get_workflow(self, workflow_run_id: UUID) -> TailRadarWorkflowData | None: ...

    def get_workflow_for_screening_run(
        self, screening_run_id: UUID
    ) -> TailRadarWorkflowData | None: ...

    def set_workflow_lifecycle(
        self,
        *,
        workflow_run_id: UUID,
        lifecycle: TailRadarWorkflowLifecycle,
    ) -> TailRadarWorkflowData: ...

    def attach_workflow_snapshot(
        self,
        *,
        workflow_run_id: UUID,
        snapshot_run_id: UUID,
        snapshot_id: UUID,
    ) -> TailRadarWorkflowData: ...

    def attach_workflow_screening(
        self,
        *,
        workflow_run_id: UUID,
        screening_run_id: UUID,
        analysis_as_of: datetime,
        candidate_ids: Sequence[UUID],
    ) -> TailRadarWorkflowData: ...

    def list_workflow_candidate_states(
        self, workflow_run_id: UUID
    ) -> tuple[TailRadarWorkflowCandidateState, ...]: ...

    def get_candidate_workflow_state(
        self, candidate_id: UUID
    ) -> TailRadarWorkflowCandidateState | None: ...

    def set_candidate_technical_stage(
        self,
        *,
        workflow_run_id: UUID,
        candidate_id: UUID,
        status: TailRadarCandidateStageStatus,
        analysis_id: UUID | None = None,
        error_code: str | None = None,
    ) -> TailRadarWorkflowCandidateState: ...

    def set_candidate_research_stage(
        self,
        *,
        workflow_run_id: UUID,
        candidate_id: UUID,
        status: TailRadarCandidateStageStatus,
        research_id: UUID | None = None,
        error_code: str | None = None,
    ) -> TailRadarWorkflowCandidateState: ...

    def complete_workflow(
        self, *, workflow_run_id: UUID, finished_at: datetime
    ) -> TailRadarWorkflowData: ...

    def fail_workflow(
        self,
        *,
        workflow_run_id: UUID,
        finished_at: datetime,
        error_stage: str,
        error_code: str,
    ) -> TailRadarWorkflowData: ...


class TailRadarDataRepository(TailRadarRepository, TailRadarWorkflowRepository, Protocol):
    """Combined persistence boundary used only by composed reads and orchestration wiring."""
