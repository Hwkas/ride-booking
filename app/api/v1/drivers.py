from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, DbSession, DriverUser
from app.api.errors import error_responses
from app.schemas.common import Page, PaginationParams
from app.schemas.driver import AvailabilityUpdate, DriverProfileCreate, DriverRead
from app.services.driver import DriverService


router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post(
    "/profile",
    response_model=DriverRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create your driver profile",
    responses=error_responses(401, 403, 409, 422),
)
async def create_profile(
    data: DriverProfileCreate, user: DriverUser, session: DbSession
) -> DriverRead:
    """Register your vehicle. The profile starts offline."""
    driver = await DriverService(session).create_profile(user, data)
    return DriverRead.from_model(driver)


@router.get(
    "/me",
    response_model=DriverRead,
    summary="Your driver profile",
    responses=error_responses(401, 403, 404),
)
async def read_my_profile(user: DriverUser, session: DbSession) -> DriverRead:
    """Return the caller's driver profile."""
    driver = await DriverService(session).get_profile(user)
    return DriverRead.from_model(driver)


@router.patch(
    "/me/availability",
    response_model=DriverRead,
    summary="Go online/offline and update location",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def update_availability(
    data: AvailabilityUpdate, user: DriverUser, session: DbSession
) -> DriverRead:
    """Toggle availability. Going online is refused while you have an active ride."""
    driver = await DriverService(session).update_availability(user, data)
    return DriverRead.from_model(driver)


@router.get(
    "",
    response_model=Page[DriverRead],
    summary="List drivers (admin)",
    responses=error_responses(401, 403, 422),
)
async def list_drivers(
    _admin: AdminUser,
    session: DbSession,
    page: Annotated[PaginationParams, Query()],
    is_available: Annotated[
        bool | None, Query(description="Filter by availability.")
    ] = None,
) -> Page[DriverRead]:
    """All drivers, newest first."""
    return await DriverService(session).list_drivers(
        is_available=is_available, page=page
    )
