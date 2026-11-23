from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import async_engine, sync_engine


DESCRIPTION = """
Ride booking with immediate driver assignment.

**Flow:** a rider requests a ride → the nearest available driver is assigned
in the same transaction (or `409 NO_DRIVER_AVAILABLE`, nothing saved) → the
driver starts and completes it, or it is cancelled before pickup.

**Auth:** `POST /auth/login` returns a JWT; click **Authorize** and paste it.

**Errors** always look like
`{"error": {"code": "...", "message": "...", "details": ...}}`.
"""

OPENAPI_TAGS = [
    {"name": "auth", "description": "Register and log in."},
    {"name": "users", "description": "The current user."},
    {
        "name": "drivers",
        "description": "Driver profile, availability, ride history and earnings; "
        "admin listing.",
    },
    {
        "name": "rides",
        "description": "Request a ride and move it through its lifecycle.",
    },
    {"name": "system", "description": "Health check."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Release database connection pools on shutdown."""
    yield
    await async_engine.dispose()
    sync_engine.dispose()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=__version__,
        openapi_tags=OPENAPI_TAGS,
        debug=settings.debug,
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
