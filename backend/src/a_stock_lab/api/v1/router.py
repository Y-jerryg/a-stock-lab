from fastapi import APIRouter

from a_stock_lab.api.v1.routes.health import router as health_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
