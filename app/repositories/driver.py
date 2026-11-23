from decimal import Decimal

from sqlalchemy import Float, Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, joinedload
from sqlalchemy.sql.elements import ColumnElement

from app.core.geo import EARTH_RADIUS_KM
from app.models import Driver, User


def distance_km_sql(lat: Decimal, lng: Decimal) -> ColumnElement[float]:
    """Haversine distance (km) from a point to each driver, computed in SQL.

    NULL for drivers without a known location.
    """
    lat1 = func.radians(cast(Driver.current_lat, Float))
    lng1 = func.radians(cast(Driver.current_lng, Float))
    lat2 = func.radians(float(lat))
    lng2 = func.radians(float(lng))
    a = func.power(func.sin((lat2 - lat1) / 2), 2) + func.cos(lat1) * func.cos(
        lat2
    ) * func.power(func.sin((lng2 - lng1) / 2), 2)
    return 2 * EARTH_RADIUS_KM * func.asin(func.least(1.0, func.sqrt(a)))


class DriverRepository:
    """Data access for driver profiles."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    @staticmethod
    def _with_user() -> Select[tuple[Driver]]:
        return select(Driver).options(joinedload(Driver.user))

    async def get_by_user_id(
        self, user_id: int, *, for_update: bool = False
    ) -> Driver | None:
        """Return the driver profile of a user, optionally row-locked.

        ``for_update`` takes a row lock on the driver (not the user), so
        concurrent availability changes and ride assignment serialise.
        """
        stmt = self._with_user().where(Driver.user_id == user_id)
        if for_update:
            stmt = stmt.with_for_update(of=Driver)
        return await self.session.scalar(stmt)

    async def lock_nearest_available(self, lat: Decimal, lng: Decimal) -> Driver | None:
        """Lock and return the best available driver for a pickup point.

        Order: nearest first (drivers without a location last), then the one
        idle longest. ``FOR UPDATE SKIP LOCKED`` makes concurrent requests pass
        over a driver another transaction is already assigning instead of
        waiting for it, so two requests can never get the same driver.
        """
        stmt = (
            select(Driver)
            .join(Driver.user)
            .options(contains_eager(Driver.user))
            .where(Driver.is_available.is_(True), User.is_active.is_(True))
            .order_by(
                distance_km_sql(lat, lng).asc().nulls_last(),
                Driver.available_since.asc().nulls_last(),
                Driver.id.asc(),
            )
            .limit(1)
            .with_for_update(of=Driver, skip_locked=True)
        )
        return await self.session.scalar(stmt)

    async def plate_exists(self, license_plate: str) -> bool:
        """Return True if a driver already uses this (normalised) plate."""
        stmt = select(Driver.id).where(Driver.license_plate == license_plate)
        return await self.session.scalar(stmt) is not None

    async def add(self, driver: Driver) -> Driver:
        """Insert a driver and flush so the id is populated."""
        self.session.add(driver)
        await self.session.flush()
        return driver

    async def list_page(
        self, *, is_available: bool | None, limit: int, offset: int
    ) -> tuple[list[Driver], int]:
        """Return one page of drivers (newest first) and the total count."""
        conditions = []
        if is_available is not None:
            conditions.append(Driver.is_available.is_(is_available))

        total = await self.session.scalar(
            select(func.count()).select_from(Driver).where(*conditions)
        )
        rows = await self.session.scalars(
            self._with_user()
            .where(*conditions)
            .order_by(Driver.created_at.desc(), Driver.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total or 0
