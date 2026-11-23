"""Reusable schema building blocks."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    PlainSerializer,
    model_validator,
)


COORDINATE_PLACES = Decimal("0.000001")  # matches Numeric(9, 6) in the DB


def _quantize_coordinate(value: Decimal) -> Decimal:
    return value.quantize(COORDINATE_PLACES, rounding=ROUND_HALF_UP)


# Coordinates: validated as Decimal (exact, matches the DB column), returned to
# clients as plain JSON numbers.
_as_float = PlainSerializer(float, return_type=float, when_used="json")
Latitude = Annotated[
    Decimal,
    Field(ge=-90, le=90, examples=[12.9716]),
    AfterValidator(_quantize_coordinate),
    _as_float,
]
Longitude = Annotated[
    Decimal,
    Field(ge=-180, le=180, examples=[77.5946]),
    AfterValidator(_quantize_coordinate),
    _as_float,
]

# Money: exact Decimal, serialised as a string so no precision is lost.
Money = Annotated[
    Decimal,
    PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="json"),
]


class OptionalLocation(BaseModel):
    """Latitude and longitude, both given or both omitted."""

    lat: Latitude | None = None
    lng: Longitude | None = None

    @model_validator(mode="after")
    def _both_or_neither(self) -> "OptionalLocation":
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must be provided together.")
        return self


class PaginationParams(BaseModel):
    """Limit/offset query parameters."""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class Page[T](BaseModel):
    """A page of results plus the total number of matches."""

    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class DateRange:
    """Inclusive calendar-day range in UTC; either end may be open."""

    start: date | None = None
    end: date | None = None

    @property
    def start_at(self) -> datetime | None:
        """Inclusive lower bound: midnight UTC at the start of ``start``."""
        return datetime.combine(self.start, time.min, UTC) if self.start else None

    @property
    def end_before(self) -> datetime | None:
        """Exclusive upper bound: midnight UTC after ``end``."""
        if self.end is None:
            return None
        return datetime.combine(self.end + timedelta(days=1), time.min, UTC)
