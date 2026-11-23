from typing import Annotated

from fastapi import APIRouter, Body, Path, status

from app.api.deps import CurrentUser, DbSession, RiderUser
from app.api.errors import error_responses
from app.schemas.ride import RideCancel, RideCreate, RideRead
from app.services.ride import RideService
from app.services.ride_lifecycle import RideAction


router = APIRouter(prefix="/rides", tags=["rides"])

RideId = Annotated[int, Path(ge=1, description="Ride id.")]
LIFECYCLE_ERRORS = error_responses(401, 403, 404, 409, 422)


@router.post(
    "",
    response_model=RideRead,
    status_code=status.HTTP_201_CREATED,
    summary="Request a ride",
    responses=error_responses(401, 403, 409, 422),
)
async def request_ride(
    data: RideCreate, rider: RiderUser, session: DbSession
) -> RideRead:
    """Assign the nearest available driver immediately.

    Returns 409 `NO_DRIVER_AVAILABLE` (nothing is saved) when every driver is
    busy or offline, and 409 `ACTIVE_RIDE_EXISTS` if you already have a ride.
    """
    ride = await RideService(session).request_ride(rider, data)
    return RideRead.from_model(ride)


@router.post(
    "/{ride_id}/start",
    response_model=RideRead,
    summary="Start a ride (assigned driver)",
    responses=LIFECYCLE_ERRORS,
)
async def start_ride(
    ride_id: RideId, user: CurrentUser, session: DbSession
) -> RideRead:
    """Pick up the rider: `assigned` → `in_progress`."""
    ride = await RideService(session).transition(user, ride_id, RideAction.START)
    return RideRead.from_model(ride)


@router.post(
    "/{ride_id}/complete",
    response_model=RideRead,
    summary="Complete a ride (assigned driver)",
    responses=LIFECYCLE_ERRORS,
)
async def complete_ride(
    ride_id: RideId, user: CurrentUser, session: DbSession
) -> RideRead:
    """Drop off the rider: `in_progress` → `completed`.

    Sets the final fare and puts the driver back online.
    """
    ride = await RideService(session).transition(user, ride_id, RideAction.COMPLETE)
    return RideRead.from_model(ride)


@router.post(
    "/{ride_id}/cancel",
    response_model=RideRead,
    summary="Cancel a ride (rider, assigned driver or admin)",
    responses=LIFECYCLE_ERRORS,
)
async def cancel_ride(
    ride_id: RideId,
    user: CurrentUser,
    session: DbSession,
    data: Annotated[RideCancel | None, Body()] = None,
) -> RideRead:
    """Cancel before pickup: `assigned` → `cancelled`. Frees the driver."""
    ride = await RideService(session).transition(
        user,
        ride_id,
        RideAction.CANCEL,
        cancellation_reason=data.reason if data else None,
    )
    return RideRead.from_model(ride)
