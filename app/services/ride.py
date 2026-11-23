from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ActiveRideExistsError, NoDriverAvailableError
from app.models import Ride, RideStatus, User
from app.repositories.driver import DriverRepository
from app.repositories.ride import RideRepository
from app.schemas.ride import RideCreate
from app.services.pricing import estimate_fare, trip_distance_km


RIDER_ACTIVE_RIDE_MESSAGE = "You already have an active ride."


def _violated_constraint(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


class RideService:
    """Ride requests and driver assignment."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the service on the request's session."""
        self.session = session
        self.rides = RideRepository(session)
        self.drivers = DriverRepository(session)

    async def request_ride(self, rider: User, data: RideCreate) -> Ride:
        """Assign the best available driver and create the ride, atomically.

        Either a driver is assigned and the ride is created as ``ASSIGNED``, or
        ``NoDriverAvailableError`` is raised and nothing is persisted. There is
        no pending state and no queue.
        """
        if await self.rides.rider_has_active_ride(rider.id):
            raise ActiveRideExistsError(RIDER_ACTIVE_RIDE_MESSAGE)

        pickup = (data.pickup.lat, data.pickup.lng)
        dropoff = (data.dropoff.lat, data.dropoff.lng)
        distance = trip_distance_km(pickup, dropoff)

        driver = await self.drivers.lock_nearest_available(*pickup)
        if driver is None:
            raise NoDriverAvailableError()

        driver.is_available = False
        driver.available_since = None

        ride = Ride(
            rider_id=rider.id,
            driver_id=driver.id,
            pickup_address=data.pickup.address,
            pickup_lat=data.pickup.lat,
            pickup_lng=data.pickup.lng,
            dropoff_address=data.dropoff.address,
            dropoff_lat=data.dropoff.lat,
            dropoff_lng=data.dropoff.lng,
            distance_km=distance,
            fare_estimate=estimate_fare(distance),
            status=RideStatus.ASSIGNED,
        )
        try:
            await self.rides.add(ride)
        except IntegrityError as exc:
            # Safety net for races the checks above cannot see; the database's
            # partial unique indexes are the final word.
            if _violated_constraint(exc) == "uq_rides_rider_active":
                raise ActiveRideExistsError(RIDER_ACTIVE_RIDE_MESSAGE) from exc
            if _violated_constraint(exc) == "uq_rides_driver_active":
                raise NoDriverAvailableError() from exc
            raise

        ride.driver = driver
        return ride
