from fastapi import APIRouter

from app.api import health, incidents, simulated_logs, simulated_metrics

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(incidents.router)
api_router.include_router(simulated_logs.router)
api_router.include_router(simulated_metrics.router)
