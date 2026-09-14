from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from a_stock_lab.api.errors import ApplicationError
from a_stock_lab.api.v1.schemas.tail_radar import (
    TailRadarCandidateDetailResponse,
    TailRadarCandidateListResponse,
    TailRadarCandidateSummaryResponse,
    TailRadarOnDemandResearchAvailabilityResponse,
    TailRadarRunListResponse,
    TailRadarRunResponse,
    TailRadarRunSummaryResponse,
    TailRadarSnapshotMetricsResponse,
    TailRadarWorkflowResponse,
)
from a_stock_lab.api.v1.services.tail_radar import get_tail_radar_query_service
from a_stock_lab.core.config import Settings, get_settings
from a_stock_lab.features.tail_radar.application.queries import TailRadarQueryService

router = APIRouter(prefix="/tail-radar", tags=["tail-radar"])
QueryService = Annotated[TailRadarQueryService, Depends(get_tail_radar_query_service)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.get(
    "/research-availability",
    response_model=TailRadarOnDemandResearchAvailabilityResponse,
)
def research_availability(
    settings: SettingsDependency,
) -> TailRadarOnDemandResearchAvailabilityResponse:
    return TailRadarOnDemandResearchAvailabilityResponse(
        enabled=settings.tail_radar_on_demand_research_enabled,
        model_identifier=settings.openai_research_model,
    )


@router.get("/runs/latest", response_model=TailRadarRunResponse)
def latest_run(service: QueryService) -> TailRadarRunResponse:
    run = service.latest_run()
    if run is None:
        raise ApplicationError(
            code="tail_radar_run_not_found",
            message="No Tail Radar run has been persisted.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return TailRadarRunResponse.from_data(run)


@router.get("/runs", response_model=TailRadarRunListResponse)
def list_runs(
    service: QueryService,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TailRadarRunListResponse:
    result = service.list_runs(offset=(page - 1) * page_size, limit=page_size)
    return TailRadarRunListResponse(
        items=tuple(TailRadarRunResponse.from_data(item) for item in result.items),
        total=result.total,
        page=page,
        page_size=page_size,
    )


@router.get("/runs/{run_id}", response_model=TailRadarRunResponse)
def run_detail(run_id: UUID, service: QueryService) -> TailRadarRunResponse:
    run = service.get_run(run_id)
    if run is None:
        raise ApplicationError(
            code="tail_radar_run_not_found",
            message="The Tail Radar run was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return TailRadarRunResponse.from_data(run)


@router.get("/runs/{run_id}/candidates", response_model=TailRadarCandidateListResponse)
def candidate_list(
    run_id: UUID,
    service: QueryService,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TailRadarCandidateListResponse:
    if service.get_run(run_id) is None:
        raise ApplicationError(
            code="tail_radar_run_not_found",
            message="The Tail Radar run was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    result = service.list_candidate_overviews(
        run_id=run_id,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return TailRadarCandidateListResponse(
        items=tuple(TailRadarCandidateSummaryResponse.from_overview(item) for item in result.items),
        total=result.total,
        page=page,
        page_size=page_size,
    )


@router.get("/runs/{run_id}/summary", response_model=TailRadarRunSummaryResponse)
def run_summary(run_id: UUID, service: QueryService) -> TailRadarRunSummaryResponse:
    run = service.get_run(run_id)
    if run is None:
        raise ApplicationError(
            code="tail_radar_run_not_found",
            message="The Tail Radar run was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    snapshot = service.get_snapshot(run.snapshot_id)
    if snapshot is None:
        raise ApplicationError(
            code="tail_radar_snapshot_not_found",
            message="The Tail Radar source snapshot was not found.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    workflow = service.get_workflow_for_run(run_id)
    return TailRadarRunSummaryResponse(
        run=TailRadarRunResponse.from_data(run),
        workflow=None if workflow is None else TailRadarWorkflowResponse.from_data(workflow),
        snapshot=TailRadarSnapshotMetricsResponse.from_data(snapshot),
    )


@router.get("/candidates/{candidate_id}", response_model=TailRadarCandidateDetailResponse)
def candidate_detail(
    candidate_id: UUID,
    service: QueryService,
) -> TailRadarCandidateDetailResponse:
    candidate = service.get_candidate(candidate_id)
    if candidate is None:
        raise ApplicationError(
            code="tail_radar_candidate_not_found",
            message="The Tail Radar candidate was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return TailRadarCandidateDetailResponse.from_data(
        candidate,
        service.get_latest_intraday_analysis(candidate_id),
        service.get_latest_research(candidate_id),
        service.get_candidate_workflow_state(candidate_id),
    )
