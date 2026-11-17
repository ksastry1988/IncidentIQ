from fastapi import FastAPI

from app.api.router import api_router
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory. Pass `settings` to override configuration (e.g. in tests)."""
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.state.settings = settings
    app.include_router(api_router)
    return app


def app_factory() -> FastAPI:
    """Uvicorn entry point: `uvicorn app.main:app_factory --factory`."""
    return create_app()
