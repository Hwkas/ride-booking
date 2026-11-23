from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Driver


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

    async def plate_exists(self, license_plate: str) -> bool:
        """Return True if a driver already uses this (normalised) plate."""
        stmt = select(Driver.id).where(Driver.license_plate == license_plate)
        return await self.session.scalar(stmt) is not None

    async def add(self, driver: Driver) -> Driver:
        """Insert a driver and flush so the id is populated."""
        self.session.add(driver)
        await self.session.flush()
        return driver

    async def list(
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
