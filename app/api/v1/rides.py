from fastapi import APIRouter, status

from app.api.deps import DbSession, RiderUser
from app.api.errors import error_responses
from app.schemas.ride import RideCreate, RideRead
from app.services.ride import RideService


router = APIRouter(prefix="/rides", tags=["rides"])


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
