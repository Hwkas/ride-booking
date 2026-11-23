import re

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from app.models import Driver
from app.schemas.common import Latitude, Longitude, OptionalLocation


_PLATE_RE = re.compile(r"^[A-Z0-9]{2,15}$")


def _normalize_plate(value: str) -> str:
    plate = re.sub(r"[\s-]", "", value).upper()
    if not _PLATE_RE.fullmatch(plate):
        raise ValueError(
            "License plate must be 2-15 letters or digits (spaces/hyphens ignored)."
        )
    return plate


LicensePlate = Annotated[
    str, StringConstraints(max_length=30), AfterValidator(_normalize_plate)
]


class DriverProfileCreate(BaseModel):
    """Vehicle details for a new driver profile. Profiles start offline."""

    vehicle_model: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ] = Field(examples=["Toyota Prius"])
    license_plate: LicensePlate = Field(examples=["KA-01 AB 1234"])


class AvailabilityUpdate(OptionalLocation):
    """Go online/offline, optionally reporting the current location."""

    is_available: bool


class DriverRead(BaseModel):
    """Driver profile as returned by the API."""

    id: int
    user_id: int
    full_name: str
    vehicle_model: str
    license_plate: str
    is_available: bool
    available_since: datetime | None
    current_lat: Latitude | None
    current_lng: Longitude | None
    created_at: datetime

    @classmethod
    def from_model(cls, driver: Driver) -> "DriverRead":
        """Build from an ORM driver whose ``user`` relationship is loaded."""
        return cls(
            id=driver.id,
            user_id=driver.user_id,
            full_name=driver.user.full_name,
            vehicle_model=driver.vehicle_model,
            license_plate=driver.license_plate,
            is_available=driver.is_available,
            available_since=driver.available_since,
            current_lat=driver.current_lat,
            current_lng=driver.current_lng,
            created_at=driver.created_at,
        )
