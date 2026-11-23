from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from app.models import Ride, RideStatus
from app.schemas.common import Latitude, Longitude, Money


Address = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
Kilometres = Annotated[
    Decimal, PlainSerializer(float, return_type=float, when_used="json")
]


class Place(BaseModel):
    """A named point on the map."""

    address: Address = Field(examples=["MG Road, Bengaluru"])
    lat: Latitude
    lng: Longitude


class RideCreate(BaseModel):
    """A rider's request for a ride."""

    pickup: Place
    dropoff: Place

    @model_validator(mode="after")
    def _distinct_points(self) -> "RideCreate":
        if (self.pickup.lat, self.pickup.lng) == (self.dropoff.lat, self.dropoff.lng):
            raise ValueError("Pickup and dropoff must be different locations.")
        return self


class RideDriver(BaseModel):
    """The assigned driver, as shown to the rider."""

    id: int
    full_name: str
    vehicle_model: str
    license_plate: str


class RideRead(BaseModel):
    """A ride as returned by the API."""

    id: int
    status: RideStatus
    rider_id: int
    driver: RideDriver
    pickup: Place
    dropoff: Place
    distance_km: Kilometres
    fare_estimate: Money
    final_fare: Money | None
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None

    @classmethod
    def from_model(cls, ride: Ride) -> "RideRead":
        """Build from an ORM ride with ``driver`` and ``driver.user`` loaded."""
        return cls(
            id=ride.id,
            status=ride.status,
            rider_id=ride.rider_id,
            driver=RideDriver(
                id=ride.driver.id,
                full_name=ride.driver.user.full_name,
                vehicle_model=ride.driver.vehicle_model,
                license_plate=ride.driver.license_plate,
            ),
            pickup=Place(
                address=ride.pickup_address, lat=ride.pickup_lat, lng=ride.pickup_lng
            ),
            dropoff=Place(
                address=ride.dropoff_address,
                lat=ride.dropoff_lat,
                lng=ride.dropoff_lng,
            ),
            distance_km=ride.distance_km,
            fare_estimate=ride.fare_estimate,
            final_fare=ride.final_fare,
            requested_at=ride.created_at,
            started_at=ride.started_at,
            completed_at=ride.completed_at,
            cancelled_at=ride.cancelled_at,
            cancellation_reason=ride.cancellation_reason,
        )
