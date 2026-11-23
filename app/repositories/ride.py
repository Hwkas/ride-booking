from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, Select, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager
from sqlalchemy.sql.elements import ColumnElement

from app.models import Driver, Ride, RideStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class RideFilters:
    """Which rides to list. ``None`` means "don't filter on this"."""

    rider_id: int | None = None
    driver_id: int | None = None
    statuses: Sequence[RideStatus] | None = None
    requested_from: datetime | None = None  # inclusive
    requested_to: datetime | None = None  # exclusive

    def conditions(self) -> list[ColumnElement[bool]]:
        """SQL WHERE clauses for the set filters."""
        clauses: list[ColumnElement[bool]] = []
        if self.rider_id is not None:
            clauses.append(Ride.rider_id == self.rider_id)
        if self.driver_id is not None:
            clauses.append(Ride.driver_id == self.driver_id)
        if self.statuses:
            clauses.append(Ride.status.in_(self.statuses))
        if self.requested_from is not None:
            clauses.append(Ride.created_at >= self.requested_from)
        if self.requested_to is not None:
            clauses.append(Ride.created_at < self.requested_to)
        return clauses


class RideRepository:
    """Data access for rides."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    @staticmethod
    def _with_driver() -> Select[tuple[Ride]]:
        """Rides with their driver and the driver's user loaded in one query."""
        return (
            select(Ride)
            .join(Ride.driver)
            .join(Driver.user)
            .options(contains_eager(Ride.driver).contains_eager(Driver.user))
        )

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

    async def get(self, ride_id: int) -> Ride | None:
        """Return a ride with its driver loaded (no locking)."""
        return await self.session.scalar(self._with_driver().where(Ride.id == ride_id))

    async def get_for_update(self, ride_id: int) -> Ride | None:
        """Return a ride with its driver (and driver's user), locking both rows.

        Lock order is always ride, then driver. Assignment and availability
        changes only lock the driver row, so no lock cycle (deadlock) exists.
        """
        stmt = (
            self._with_driver()
            .where(Ride.id == ride_id)
            .with_for_update(of=(Ride, Driver))
        )
        return await self.session.scalar(stmt)

    async def list_page(
        self, filters: RideFilters, *, limit: int, offset: int
    ) -> tuple[list[Ride], int]:
        """Return one page of matching rides (newest first) and the total."""
        conditions = filters.conditions()
        total = await self.session.scalar(
            select(func.count()).select_from(Ride).where(*conditions)
        )
        rows = await self.session.scalars(
            self._with_driver()
            .where(*conditions)
            .order_by(Ride.created_at.desc(), Ride.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total or 0

    # --- Earnings -----------------------------------------------------------

    @staticmethod
    def _completed_by(
        driver_id: int,
        completed_from: datetime | None,
        completed_before: datetime | None,
    ) -> list[ColumnElement[bool]]:
        clauses = [Ride.driver_id == driver_id, Ride.status == RideStatus.COMPLETED]
        if completed_from is not None:
            clauses.append(Ride.completed_at >= completed_from)
        if completed_before is not None:
            clauses.append(Ride.completed_at < completed_before)
        return clauses

    async def earnings_totals(
        self,
        driver_id: int,
        *,
        completed_from: datetime | None,
        completed_before: datetime | None,
    ) -> tuple[Decimal, int]:
        """Return ``(sum of final fares, number of rides)`` for completed rides."""
        stmt = select(
            func.coalesce(func.sum(Ride.final_fare), 0), func.count(Ride.id)
        ).where(*self._completed_by(driver_id, completed_from, completed_before))
        total, count = (await self.session.execute(stmt)).one()
        return Decimal(total), count

    async def earnings_by_period(
        self,
        driver_id: int,
        *,
        unit: str,
        completed_from: datetime | None,
        completed_before: datetime | None,
    ) -> list[tuple[date, Decimal, int]]:
        """Return ``(period start, earnings, rides)`` per day/week/month, oldest first.

        Periods are computed in UTC regardless of the database session's time
        zone. Only periods with at least one completed ride are returned.
        """
        period = cast(
            func.date_trunc(unit, func.timezone("UTC", Ride.completed_at)), Date
        ).label("period")
        stmt = (
            select(period, func.sum(Ride.final_fare), func.count(Ride.id))
            .where(*self._completed_by(driver_id, completed_from, completed_before))
            .group_by(period)
            .order_by(period)
        )
        rows = await self.session.execute(stmt)
        return [(p, Decimal(total), count) for p, total, count in rows]
