"""Distance and fare calculation (pure functions)."""

from decimal import ROUND_HALF_UP, Decimal

from app.core.config import get_settings
from app.core.geo import haversine_km


CENTS = Decimal("0.01")


def trip_distance_km(
    pickup: tuple[Decimal, Decimal], dropoff: tuple[Decimal, Decimal]
) -> Decimal:
    """Straight-line trip distance rounded to 2 decimals (no routing service)."""
    km = haversine_km(
        float(pickup[0]), float(pickup[1]), float(dropoff[0]), float(dropoff[1])
    )
    return Decimal(str(km)).quantize(CENTS, rounding=ROUND_HALF_UP)


def estimate_fare(distance_km: Decimal) -> Decimal:
    """Base fare plus a per-kilometre rate, rounded to cents."""
    settings = get_settings()
    fare = settings.fare_base + settings.fare_per_km * distance_km
    return fare.quantize(CENTS, rounding=ROUND_HALF_UP)
