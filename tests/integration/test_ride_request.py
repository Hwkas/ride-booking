from datetime import UTC, datetime, timedelta

import pytest

from sqlalchemy import func, select

from app.models import Ride, RideStatus, UserRole
from tests.factories import auth_headers, create_driver, create_ride, create_user


# Pickup at MG Road, Bengaluru; drivers are placed relative to it.
PICKUP = {"address": "MG Road, Bengaluru", "lat": 12.9756, "lng": 77.6059}
DROPOFF = {"address": "Indiranagar, Bengaluru", "lat": 12.9784, "lng": 77.6408}
NEAR = ("12.976000", "77.606000")  # ~50 m away
MID = ("12.990000", "77.620000")  # ~2 km away
FAR = ("13.100000", "77.700000")  # ~17 km away


def ride_payload(**overrides):
    return {"pickup": PICKUP, "dropoff": DROPOFF} | overrides


@pytest.fixture
async def rider(db_session):
    return await create_user(db_session, role=UserRole.RIDER)


async def request_ride(client, rider, **overrides):
    return await client.post(
        "/rides", json=ride_payload(**overrides), headers=auth_headers(rider)
    )


async def ride_count(db_session) -> int:
    return await db_session.scalar(select(func.count()).select_from(Ride))


# --- Happy path ---------------------------------------------------------------


async def test_request_assigns_driver_and_creates_ride(client, db_session, rider):
    driver = await create_driver(db_session, lat=NEAR[0], lng=NEAR[1])

    response = await request_ride(client, rider)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "assigned"
    assert body["rider_id"] == rider.id
    assert body["driver"]["id"] == driver.id
    assert body["driver"]["license_plate"] == driver.license_plate
    assert body["pickup"] == PICKUP
    assert body["dropoff"] == DROPOFF
    assert body["distance_km"] == 3.79
    assert body["fare_estimate"] == "7.05"  # money is a string
    assert body["final_fare"] is None
    assert body["requested_at"] is not None
    assert body["started_at"] is None

    # The driver is now busy.
    await db_session.refresh(driver)
    assert driver.is_available is False
    assert driver.available_since is None


async def test_nearest_driver_wins(client, db_session, rider):
    await create_driver(db_session, lat=FAR[0], lng=FAR[1])
    nearest = await create_driver(db_session, lat=NEAR[0], lng=NEAR[1])
    await create_driver(db_session, lat=MID[0], lng=MID[1])

    response = await request_ride(client, rider)

    assert response.json()["driver"]["id"] == nearest.id


async def test_drivers_without_location_are_used_last(client, db_session, rider):
    await create_driver(db_session, lat=None, lng=None)
    located = await create_driver(db_session, lat=FAR[0], lng=FAR[1])

    response = await request_ride(client, rider)

    assert response.json()["driver"]["id"] == located.id


async def test_driver_without_location_still_gets_ride_if_only_one(
    client, db_session, rider
):
    unlocated = await create_driver(db_session, lat=None, lng=None)

    response = await request_ride(client, rider)

    assert response.json()["driver"]["id"] == unlocated.id


async def test_equal_distance_goes_to_longest_idle_driver(client, db_session, rider):
    now = datetime.now(UTC)
    await create_driver(
        db_session, lat=NEAR[0], lng=NEAR[1], available_since=now - timedelta(minutes=5)
    )
    longest_idle = await create_driver(
        db_session, lat=NEAR[0], lng=NEAR[1], available_since=now - timedelta(hours=1)
    )

    response = await request_ride(client, rider)

    assert response.json()["driver"]["id"] == longest_idle.id


async def test_offline_busy_and_disabled_drivers_are_skipped(client, db_session, rider):
    await create_driver(db_session, available=False, lat=NEAR[0], lng=NEAR[1])
    disabled_user = await create_user(db_session, role=UserRole.DRIVER, is_active=False)
    await create_driver(db_session, user=disabled_user, lat=NEAR[0], lng=NEAR[1])
    eligible = await create_driver(db_session, lat=FAR[0], lng=FAR[1])

    response = await request_ride(client, rider)

    assert response.json()["driver"]["id"] == eligible.id


# --- No driver ------------------------------------------------------------------


async def test_no_driver_available_is_409_and_saves_nothing(client, db_session, rider):
    await create_driver(db_session, available=False)

    response = await request_ride(client, rider)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DRIVER_AVAILABLE"
    assert await ride_count(db_session) == 0


async def test_no_drivers_at_all_is_409(client, rider):
    response = await request_ride(client, rider)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DRIVER_AVAILABLE"


async def test_each_driver_is_assigned_only_once(client, db_session):
    await create_driver(db_session)
    first, second = [await create_user(db_session) for _ in range(2)]

    assert (await request_ride(client, first)).status_code == 201
    response = await request_ride(client, second)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DRIVER_AVAILABLE"


# --- One active ride per rider ----------------------------------------------------


@pytest.mark.parametrize("status", [RideStatus.ASSIGNED, RideStatus.IN_PROGRESS])
async def test_rider_with_active_ride_is_409(client, db_session, rider, status):
    await create_ride(db_session, rider=rider, status=status)
    await create_driver(db_session)

    response = await request_ride(client, rider)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACTIVE_RIDE_EXISTS"
    assert await ride_count(db_session) == 1


@pytest.mark.parametrize("status", [RideStatus.COMPLETED, RideStatus.CANCELLED])
async def test_rider_can_request_again_after_ride_ends(
    client, db_session, rider, status
):
    await create_ride(db_session, rider=rider, status=status)
    await create_driver(db_session)

    response = await request_ride(client, rider)

    assert response.status_code == 201


# --- Access & validation ---------------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.DRIVER, UserRole.ADMIN])
async def test_only_riders_can_request(client, db_session, role):
    user = await create_user(db_session, role=role)

    response = await request_ride(client, user)

    assert response.status_code == 403


async def test_request_requires_auth(client):
    response = await client.post("/rides", json=ride_payload())

    assert response.status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"dropoff": PICKUP},  # same place
        {"pickup": PICKUP | {"lat": 90.5}},
        {"dropoff": DROPOFF | {"lng": -180.1}},
        {"pickup": PICKUP | {"address": "  "}},
        {"pickup": {"lat": 1, "lng": 1}},  # no address
        {"dropoff": None},
    ],
)
async def test_request_validation(client, db_session, rider, overrides):
    await create_driver(db_session)

    response = await request_ride(client, rider, **overrides)

    assert response.status_code == 422
    assert await ride_count(db_session) == 0
