from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DriverProfileNotFoundError
from app.models import RideStatus, User
from app.repositories.driver import DriverRepository
from app.repositories.ride import RideFilters, RideRepository
from app.schemas.common import DateRange, Page, PaginationParams
from app.schemas.earnings import EarningsBucket, EarningsPeriod, EarningsSummary
from app.schemas.ride import RideRead


CENTS = Decimal("0.01")


class DriverHistoryService:
    """A driver's own ride history and earnings."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the service on the request's session."""
        self.session = session
        self.drivers = DriverRepository(session)
        self.rides = RideRepository(session)

    async def _driver_id(self, user: User) -> int:
        driver = await self.drivers.get_by_user_id(user.id)
        if driver is None:
            raise DriverProfileNotFoundError()
        return driver.id

    async def ride_history(
        self,
        user: User,
        *,
        statuses: list[RideStatus] | None,
        requested: DateRange,
        page: PaginationParams,
    ) -> Page[RideRead]:
        """All rides ever assigned to the driver, newest first."""
        filters = RideFilters(
            driver_id=await self._driver_id(user),
            statuses=statuses,
            requested_from=requested.start_at,
            requested_to=requested.end_before,
        )
        rides, total = await self.rides.list_page(
            filters, limit=page.limit, offset=page.offset
        )
        return Page[RideRead](
            items=[RideRead.from_model(r) for r in rides],
            total=total,
            limit=page.limit,
            offset=page.offset,
        )

    async def earnings(
        self,
        user: User,
        *,
        completed: DateRange,
        group_by: EarningsPeriod | None,
    ) -> EarningsSummary:
        """Sum of final fares over completed rides, aggregated in SQL.

        Cancelled and unfinished rides earn nothing. A ride counts in the
        period in which it was completed.
        """
        driver_id = await self._driver_id(user)
        window = {
            "completed_from": completed.start_at,
            "completed_before": completed.end_before,
        }

        total, count = await self.rides.earnings_totals(driver_id, **window)
        average = (
            (total / count).quantize(CENTS, ROUND_HALF_UP) if count else Decimal(0)
        )

        breakdown = None
        if group_by is not None:
            rows = await self.rides.earnings_by_period(
                driver_id, unit=group_by.value, **window
            )
            breakdown = [
                EarningsBucket(period=period, earnings=earnings, rides=rides)
                for period, earnings, rides in rows
            ]

        return EarningsSummary(
            from_=completed.start,
            to=completed.end,
            group_by=group_by,
            total_earnings=total,
            completed_rides=count,
            average_fare=average,
            breakdown=breakdown,
        )
