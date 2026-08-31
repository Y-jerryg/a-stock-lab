from pydantic import BaseModel, ConfigDict, Field

from a_stock_lab.features.tail_radar.application.intraday_models import (
    TailRadarIntradayAnalysisData,
)
from a_stock_lab.features.tail_radar.application.models import TailRadarCandidateData
from a_stock_lab.features.tail_radar.application.orchestration_models import (
    TailRadarWorkflowCandidateState,
)


class TailRadarCandidateOverviewData(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate: TailRadarCandidateData
    intraday_analysis: TailRadarIntradayAnalysisData | None
    workflow_state: TailRadarWorkflowCandidateState | None


class TailRadarCandidateOverviewPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[TailRadarCandidateOverviewData, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
