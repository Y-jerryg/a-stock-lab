from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from a_stock_lab.api.v1.schemas.health import HealthResponse
from a_stock_lab.api.v1.services.health import HealthService, get_health_service

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
def health(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse | JSONResponse:
    result = service.check()
    if result.status == "degraded":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=result.model_dump(mode="json"),
        )
    return result
