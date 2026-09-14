from a_stock_lab.features.tail_radar.application.research_models import (
    ResearchProviderRequest,
    ResearchProviderResult,
)
from a_stock_lab.features.tail_radar.domain.errors import ResearchProviderUnavailableError


class UnavailableResearchProvider:
    """Fail one AI stage predictably without preventing deterministic capture stages."""

    def __init__(self, *, provider_id: str, model_id: str, reason: str) -> None:
        self._provider_id = provider_id
        self._model_id = model_id
        self._reason = reason

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def research(self, request: ResearchProviderRequest) -> ResearchProviderResult:
        del request
        raise ResearchProviderUnavailableError(self._reason)
