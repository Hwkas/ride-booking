from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.models import Driver, Ride, RideStatus


class RideRepository:
    """Data access for rides."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def driver_has_active_ride(self, driver_id: int) -> bool:
        """Return True if the driver is assigned to or driving a ride."""
        stmt = select(
            exists().where(
                Ride.driver_id == driver_id,
                Ride.status.in_(RideStatus.active()),
            )
        )
        return bool(await self.session.scalar(stmt))

    async def rider_has_active_ride(self, rider_id: int) -> bool:
        """Return True if the rider has a ride that is not finished."""
        stmt = select(
            exists().where(
                Ride.rider_id == rider_id,
                Ride.status.in_(RideStatus.active()),
            )
        )
        return bool(await self.session.scalar(stmt))

    async def add(self, ride: Ride) -> Ride:
        """Insert a ride and flush so id and timestamps are populated."""
        self.session.add(ride)
        await self.session.flush()
        return ride

    async def get_for_update(self, ride_id: int) -> Ride | None:
        """Return a ride with its driver (and driver's user), locking both rows.

        Lock order is always ride, then driver. Assignment and availability
        changes only lock the driver row, so no lock cycle (deadlock) exists.
        """
        stmt = (
            select(Ride)
            .join(Ride.driver)
            .join(Driver.user)
            .options(contains_eager(Ride.driver).contains_eager(Driver.user))
            .where(Ride.id == ride_id)
            .with_for_update(of=(Ride, Driver))
        )
        return await self.session.scalar(stmt)
