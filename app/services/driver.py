from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ActiveRideExistsError,
    DriverProfileExistsError,
    DriverProfileNotFoundError,
    LicensePlateTakenError,
)
from app.models import Driver, User
from app.repositories.driver import DriverRepository
from app.repositories.ride import RideRepository
from app.schemas.common import Page, PaginationParams
from app.schemas.driver import AvailabilityUpdate, DriverProfileCreate, DriverRead


class DriverService:
    """Driver profiles and availability."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the service on the request's session."""
        self.session = session
        self.drivers = DriverRepository(session)
        self.rides = RideRepository(session)

    async def create_profile(self, user: User, data: DriverProfileCreate) -> Driver:
        """Create the caller's driver profile (offline until they go online)."""
        if await self.drivers.get_by_user_id(user.id) is not None:
            raise DriverProfileExistsError()
        if await self.drivers.plate_exists(data.license_plate):
            raise LicensePlateTakenError()

        driver = Driver(
            user_id=user.id,
            vehicle_model=data.vehicle_model,
            license_plate=data.license_plate,
        )
        try:
            await self.drivers.add(driver)
        except IntegrityError as exc:
            # Lost a race with a concurrent request; report which rule broke.
            if "license_plate" in str(exc.orig):
                raise LicensePlateTakenError() from exc
            raise DriverProfileExistsError() from exc

        driver.user = user
        return driver

    async def get_profile(self, user: User) -> Driver:
        """Return the caller's driver profile or raise 404."""
        driver = await self.drivers.get_by_user_id(user.id)
        if driver is None:
            raise DriverProfileNotFoundError()
        return driver

    async def update_availability(self, user: User, data: AvailabilityUpdate) -> Driver:
        """Go online/offline and/or update location.

        The driver row is locked first, so this cannot interleave with a ride
        assignment (which locks the same row): a driver who was just assigned
        cannot flip themselves back to available.
        """
        driver = await self.drivers.get_by_user_id(user.id, for_update=True)
        if driver is None:
            raise DriverProfileNotFoundError()

        if data.lat is not None and data.lng is not None:
            driver.current_lat = data.lat
            driver.current_lng = data.lng

        if data.is_available and not driver.is_available:
            if await self.rides.driver_has_active_ride(driver.id):
                raise ActiveRideExistsError(
                    "Finish or cancel your current ride before going online."
                )
            driver.is_available = True
            driver.available_since = datetime.now(UTC)
        elif not data.is_available:
            driver.is_available = False
            driver.available_since = None

        await self.session.flush()
        return driver

    async def list_drivers(
        self, *, is_available: bool | None, page: PaginationParams
    ) -> Page[DriverRead]:
        """Admin view of all drivers, optionally filtered by availability."""
        drivers, total = await self.drivers.list_page(
            is_available=is_available, limit=page.limit, offset=page.offset
        )
        return Page[DriverRead](
            items=[DriverRead.from_model(d) for d in drivers],
            total=total,
            limit=page.limit,
            offset=page.offset,
        )
