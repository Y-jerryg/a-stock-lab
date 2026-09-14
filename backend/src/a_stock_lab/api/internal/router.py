from fastapi import APIRouter

from a_stock_lab.api.internal.routes.tail_radar import router as tail_radar_router

internal_api_router = APIRouter()
internal_api_router.include_router(tail_radar_router)
