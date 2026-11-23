from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ride, RideStatus


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
