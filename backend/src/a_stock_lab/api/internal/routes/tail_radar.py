from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from a_stock_lab.api.errors import ApplicationError
from a_stock_lab.api.internal.schemas.tail_radar import TailRadarResearchRequest
from a_stock_lab.api.internal.services.tail_radar import (
    UserOpenAIAPIKey,
    get_on_demand_research_service,
)
from a_stock_lab.api.v1.schemas.tail_radar import TailRadarWebResearchResponse
from a_stock_lab.features.tail_radar.application.on_demand_research_service import (
    TailRadarOnDemandResearchService,
)
from a_stock_lab.features.tail_radar.domain.errors import (
    ResearchProviderAPIError,
    ResearchProviderAuthenticationError,
    ResearchProviderInvalidResponseError,
    ResearchProviderRateLimitError,
    ResearchProviderTimeoutError,
    ResearchProviderUnavailableError,
    TailRadarCandidateNotFoundError,
    TailRadarCommitUncertainError,
    TailRadarOnDemandResearchInProgressError,
    TailRadarOnDemandResearchRetryRequiredError,
    TailRadarOnDemandResearchUnavailableError,
    TailRadarResearchConfigurationError,
)

router = APIRouter(prefix="/tail-radar", tags=["tail-radar-operations"])
ResearchService = Annotated[
    TailRadarOnDemandResearchService,
    Depends(get_on_demand_research_service),
]


@router.post(
    "/candidates/{candidate_id}/research",
    response_model=TailRadarWebResearchResponse,
)
def research_candidate(
    candidate_id: UUID,
    request: TailRadarResearchRequest,
    _: UserOpenAIAPIKey,
    service: ResearchService,
) -> TailRadarWebResearchResponse:
    try:
        result = service.execute(
            candidate_id=candidate_id,
            retry_failed=request.retry_failed,
        )
    except TailRadarCandidateNotFoundError as exc:
        raise _application_error(exc, status.HTTP_404_NOT_FOUND) from exc
    except (
        TailRadarOnDemandResearchInProgressError,
        TailRadarOnDemandResearchRetryRequiredError,
    ) as exc:
        raise _application_error(exc, status.HTTP_409_CONFLICT) from exc
    except ResearchProviderRateLimitError as exc:
        raise _application_error(exc, status.HTTP_429_TOO_MANY_REQUESTS) from exc
    except ResearchProviderAuthenticationError as exc:
        raise _application_error(exc, status.HTTP_401_UNAUTHORIZED) from exc
    except ResearchProviderTimeoutError as exc:
        raise _application_error(exc, status.HTTP_504_GATEWAY_TIMEOUT) from exc
    except (
        ResearchProviderAPIError,
        ResearchProviderInvalidResponseError,
        ResearchProviderUnavailableError,
    ) as exc:
        raise _application_error(exc, status.HTTP_502_BAD_GATEWAY) from exc
    except (
        TailRadarCommitUncertainError,
        TailRadarOnDemandResearchUnavailableError,
        TailRadarResearchConfigurationError,
    ) as exc:
        raise _application_error(exc, status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    return TailRadarWebResearchResponse.from_data(result.research)


def _application_error(error: Exception, status_code: int) -> ApplicationError:
    code = getattr(error, "code", None)
    return ApplicationError(
        code=code if isinstance(code, str) and code else type(error).__name__,
        message=str(error),
        status_code=status_code,
    )
