from fastapi import APIRouter, Response, status

from app import __version__
from app.db.session import ping
from app.schemas.health import HealthResponse


router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and database connectivity check",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(response: Response) -> HealthResponse:
    """Report service liveness and whether the database is reachable."""
    db_ok = await ping()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        database="ok" if db_ok else "unavailable",
        version=__version__,
    )
