from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.api.router import api_router
from app.config import Settings, get_settings
from app.db.session import create_database_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory. Pass `settings` to override configuration (e.g. in tests)."""
    settings = settings or get_settings()
    engine = create_database_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = create_session_factory(engine)
    app.include_router(api_router)
    return app


def app_factory() -> FastAPI:
    """Uvicorn entry point: `uvicorn app.main:app_factory --factory`."""
    return create_app()
