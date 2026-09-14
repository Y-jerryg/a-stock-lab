from typing import Annotated

from fastapi import Depends, Header, status
from pydantic import SecretStr

from a_stock_lab.api.errors import ApplicationError
from a_stock_lab.core.config import Settings, get_settings
from a_stock_lab.features.tail_radar.application.on_demand_research_service import (
    TailRadarOnDemandResearchService,
)
from a_stock_lab.features.tail_radar.factory import (
    build_tail_radar_on_demand_research_service,
)


def require_user_openai_api_key(
    x_openai_api_key: Annotated[str | None, Header(alias="X-OpenAI-API-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> SecretStr:
    if not settings.tail_radar_on_demand_research_enabled:
        raise ApplicationError(
            code="tail_radar_on_demand_research_disabled",
            message="On-demand Tail Radar research is disabled.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    supplied = (x_openai_api_key or "").strip()
    if not supplied:
        raise ApplicationError(
            code="tail_radar_user_api_key_required",
            message="An OpenAI API key is required for this one-candidate request.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return SecretStr(supplied)


UserOpenAIAPIKey = Annotated[SecretStr, Depends(require_user_openai_api_key)]


def get_on_demand_research_service(
    user_api_key: UserOpenAIAPIKey,
    settings: Settings = Depends(get_settings),
) -> TailRadarOnDemandResearchService:
    return build_tail_radar_on_demand_research_service(
        settings,
        user_api_key=user_api_key,
    )
