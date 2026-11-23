"""Small async factories for test data.

Each helper builds a valid row with sensible defaults, adds it to the session
and flushes (so ids and server defaults are populated). Override any field via
keyword arguments.
"""

from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from itertools import count
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password_sync
from app.models import Driver, Ride, RideStatus, User, UserRole


_seq = count(1)

DEFAULT_PASSWORD = "Passw0rd!"


@lru_cache
def _default_password_hash() -> str:
    return hash_password_sync(DEFAULT_PASSWORD)


def auth_headers(user: User) -> dict[str, str]:
    """Authorization header with a valid token for ``user``."""
    token, _ = create_access_token(user.id, user.role)
    return {"Authorization": f"Bearer {token}"}


async def create_user(
    session: AsyncSession,
    *,
    role: UserRole = UserRole.RIDER,
    **overrides: Any,
) -> User:
    """Create a user (rider by default)."""
    n = next(_seq)
    fields: dict[str, Any] = {
        "email": f"{role.value}{n}@example.com",
        "password_hash": _default_password_hash(),
        "full_name": f"Test {role.value.title()} {n}",
        "role": role,
    }
    fields.update(overrides)
    user = User(**fields)
    session.add(user)
    await session.flush()
    return user


async def create_driver(
    session: AsyncSession,
    *,
    user: User | None = None,
    available: bool = True,
    lat: Decimal | str | None = "12.971600",
    lng: Decimal | str | None = "77.594600",
    **overrides: Any,
) -> Driver:
    """Create a driver profile (and its user, unless one is given)."""
    if user is None:
        user = await create_user(session, role=UserRole.DRIVER)
    n = next(_seq)
    fields: dict[str, Any] = {
        "user_id": user.id,
        "vehicle_model": "Toyota Prius",
        "license_plate": f"TEST{n:04d}",
        "is_available": available,
        "available_since": datetime.now(UTC) if available else None,
        "current_lat": Decimal(lat) if lat is not None else None,
        "current_lng": Decimal(lng) if lng is not None else None,
    }
    fields.update(overrides)
    driver = Driver(**fields)
    session.add(driver)
    await session.flush()
    return driver


async def create_ride(
    session: AsyncSession,
    *,
    rider: User | None = None,
    driver: Driver | None = None,
    status: RideStatus = RideStatus.ASSIGNED,
    **overrides: Any,
) -> Ride:
    """Create a ride; lifecycle timestamps and fare are filled in to match status."""
    if rider is None:
        rider = await create_user(session, role=UserRole.RIDER)
    if driver is None:
        driver = await create_driver(session, available=False)

    now = datetime.now(UTC)
    fields: dict[str, Any] = {
        "rider_id": rider.id,
        "driver_id": driver.id,
        "pickup_address": "MG Road, Bengaluru",
        "pickup_lat": Decimal("12.975600"),
        "pickup_lng": Decimal("77.605900"),
        "dropoff_address": "Indiranagar, Bengaluru",
        "dropoff_lat": Decimal("12.978400"),
        "dropoff_lng": Decimal("77.640800"),
        "distance_km": Decimal("3.80"),
        "fare_estimate": Decimal("7.06"),
        "status": status,
    }
    if status in (RideStatus.IN_PROGRESS, RideStatus.COMPLETED):
        fields["started_at"] = now
    if status is RideStatus.COMPLETED:
        fields["completed_at"] = now
        fields["final_fare"] = overrides.get("fare_estimate", fields["fare_estimate"])
    if status is RideStatus.CANCELLED:
        fields["cancelled_at"] = now
    fields.update(overrides)

    ride = Ride(**fields)
    session.add(ride)
    await session.flush()
    return ride
