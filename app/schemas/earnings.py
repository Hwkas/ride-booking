from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.common import Money


class EarningsPeriod(StrEnum):
    """Granularity of the earnings breakdown (weeks start on Monday, UTC)."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class EarningsBucket(BaseModel):
    """Earnings for one period."""

    period: date = Field(description="First day of the period (UTC).")
    earnings: Money
    rides: int


class EarningsSummary(BaseModel):
    """A driver's earnings from completed rides in a date range."""

    from_: date | None = Field(serialization_alias="from")
    to: date | None
    group_by: EarningsPeriod | None
    total_earnings: Money
    completed_rides: int
    average_fare: Money
    breakdown: list[EarningsBucket] | None = Field(
        description="Per-period totals, oldest first; only periods with earnings. "
        "Null unless group_by is given."
    )
