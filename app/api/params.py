"""Reusable query-parameter dependencies."""

from datetime import date
from typing import Annotated

from fastapi import Depends, Query
from fastapi.exceptions import RequestValidationError

from app.schemas.common import DateRange


def date_range(
    from_: Annotated[
        date | None,
        Query(alias="from", description="First day, inclusive (YYYY-MM-DD, UTC)."),
    ] = None,
    to: Annotated[
        date | None,
        Query(description="Last day, inclusive (YYYY-MM-DD, UTC)."),
    ] = None,
) -> DateRange:
    """Parse ``from``/``to`` query parameters, rejecting reversed ranges with 422."""
    if from_ and to and from_ > to:
        raise RequestValidationError(
            [
                {
                    "loc": ("query", "to"),
                    "msg": "'to' must be on or after 'from'.",
                    "type": "value_error",
                }
            ]
        )
    return DateRange(start=from_, end=to)


DateRangeQuery = Annotated[DateRange, Depends(date_range)]
