from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ActiveRideExistsError,
    NoDriverAvailableError,
    RideNotFoundError,
)
from app.models import Ride, RideStatus, User, UserRole
from app.repositories.driver import DriverRepository
from app.repositories.ride import RideFilters, RideRepository
from app.schemas.common import Page, PaginationParams
from app.schemas.ride import RideCreate, RideRead
from app.services.pricing import estimate_fare, trip_distance_km
from app.services.ride_lifecycle import RideAction, RideActor, apply_transition


RIDER_ACTIVE_RIDE_MESSAGE = "You already have an active ride."


def _violated_constraint(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def actor_for(user: User, ride: Ride) -> RideActor | None:
    """The caller's relationship to the ride, or None if they have none.

    Requires ``ride.driver`` to be loaded.
    """
    if user.role is UserRole.ADMIN:
        return RideActor.ADMIN
    if user.role is UserRole.RIDER and ride.rider_id == user.id:
        return RideActor.RIDER
    if user.role is UserRole.DRIVER and ride.driver.user_id == user.id:
        return RideActor.DRIVER
    return None


class RideService:
    """Ride requests, driver assignment and the ride lifecycle."""

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

    async def transition(
        self,
        user: User,
        ride_id: int,
        action: RideAction,
        *,
        cancellation_reason: str | None = None,
    ) -> Ride:
        """Start, complete or cancel a ride on behalf of ``user``.

        The ride and its driver are locked first, so concurrent actions on the
        same ride are applied one at a time against the latest status.
        Callers unrelated to the ride get 404 rather than 403, so ride ids
        cannot be probed.
        """
        ride = await self.rides.get_for_update(ride_id)
        if ride is None:
            raise RideNotFoundError()
        actor = actor_for(user, ride)
        if actor is None:
            raise RideNotFoundError()

        now = datetime.now(UTC)
        transition = apply_transition(ride, action, actor, at=now)

        if action is RideAction.COMPLETE:
            # No live tracking, so the estimate is what the rider pays.
            ride.final_fare = ride.fare_estimate
        if action is RideAction.CANCEL:
            ride.cancellation_reason = cancellation_reason
        if transition.releases_driver:
            ride.driver.is_available = True
            ride.driver.available_since = now

        await self.session.flush()
        return ride

    async def get_ride(self, user: User, ride_id: int) -> Ride:
        """Return a ride the caller is involved in (or any ride, for admins)."""
        ride = await self.rides.get(ride_id)
        if ride is None or actor_for(user, ride) is None:
            raise RideNotFoundError()
        return ride

    async def list_rides(
        self,
        user: User,
        *,
        statuses: list[RideStatus] | None,
        page: PaginationParams,
    ) -> Page[RideRead]:
        """List rides visible to the caller, newest first.

        Riders see rides they requested, drivers see rides assigned to them,
        admins see every ride.
        """
        match user.role:
            case UserRole.RIDER:
                filters = RideFilters(rider_id=user.id, statuses=statuses)
            case UserRole.DRIVER:
                driver = await self.drivers.get_by_user_id(user.id)
                if driver is None:  # no profile yet, so no rides
                    return Page[RideRead](
                        items=[], total=0, limit=page.limit, offset=page.offset
                    )
                filters = RideFilters(driver_id=driver.id, statuses=statuses)
            case UserRole.ADMIN:
                filters = RideFilters(statuses=statuses)

        rides, total = await self.rides.list(
            filters, limit=page.limit, offset=page.offset
        )
        return Page[RideRead](
            items=[RideRead.from_model(r) for r in rides],
            total=total,
            limit=page.limit,
            offset=page.offset,
        )
