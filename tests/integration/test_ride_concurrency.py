"""Concurrent ride requests against real, committed transactions.

The usual ``client`` fixture shares one rolled-back connection, which cannot
model two requests racing each other. These tests use the app's real session
dependency (separate pooled connections, real commits) and clean up by
truncating the tables afterwards.
"""

import asyncio

from collections.abc import AsyncGenerator

import httpx
import pytest

from sqlalchemy import func, select, text

from app.db.session import AsyncSessionLocal
from app.models import Driver, Ride, User, UserRole
from tests.factories import auth_headers, create_driver, create_user


PAYLOAD = {
    "pickup": {"address": "MG Road", "lat": 12.9756, "lng": 77.6059},
    "dropoff": {"address": "Indiranagar", "lat": 12.9784, "lng": 77.6408},
}


@pytest.fixture
async def live_client(app, engine) -> AsyncGenerator[httpx.AsyncClient]:
    """Client using the real per-request transactions (no overrides)."""
    app.dependency_overrides.clear()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test/api/v1"
    ) as client:
        yield client
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE rides, drivers, users RESTART IDENTITY"))


async def seed(drivers: int, riders: int) -> tuple[list[Driver], list[User]]:
    """Commit drivers and riders so every request's connection can see them."""
    async with AsyncSessionLocal() as session:
        created_drivers = [await create_driver(session) for _ in range(drivers)]
        created_riders = [
            await create_user(session, role=UserRole.RIDER) for _ in range(riders)
        ]
        await session.commit()
    return created_drivers, created_riders


async def count(model) -> int:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def warm_pool(client) -> None:
    """Open pooled connections up front.

    Otherwise connection setup staggers the requests: the first one reuses an
    open connection and commits before the others have even read, so the race
    under test never happens.
    """
    await asyncio.gather(*(client.get("/health") for _ in range(5)))


async def fire(client, riders, payload=PAYLOAD) -> list[httpx.Response]:
    await warm_pool(client)
    return await asyncio.gather(
        *(client.post("/rides", json=payload, headers=auth_headers(r)) for r in riders)
    )


async def test_one_driver_many_riders_exactly_one_assignment(live_client):
    (driver,), riders = await seed(drivers=1, riders=8)

    responses = await fire(live_client, riders)

    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * 7
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} == {
        "NO_DRIVER_AVAILABLE"
    }
    assert await count(Ride) == 1
    async with AsyncSessionLocal() as session:
        stored = await session.get(Driver, driver.id)
        assert stored.is_available is False


async def test_many_drivers_many_riders_no_driver_assigned_twice(live_client):
    drivers, riders = await seed(drivers=5, riders=5)

    responses = await fire(live_client, riders)

    assert all(r.status_code == 201 for r in responses)
    assigned = [r.json()["driver"]["id"] for r in responses]
    assert sorted(assigned) == sorted(d.id for d in drivers)  # each exactly once


async def test_same_rider_double_submit_creates_one_ride(live_client):
    _, (rider,) = await seed(drivers=2, riders=1)

    responses = await fire(live_client, [rider, rider])

    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()["error"]["code"] == "ACTIVE_RIDE_EXISTS"
    assert await count(Ride) == 1
    # The losing request rolled back, so its driver is still free.
    async with AsyncSessionLocal() as session:
        free = await session.scalar(
            select(func.count()).select_from(Driver).where(Driver.is_available)
        )
        assert free == 1


async def test_live_client_commits_for_real(live_client):
    _, (rider,) = await seed(drivers=1, riders=1)

    response = await live_client.post(
        "/rides", json=PAYLOAD, headers=auth_headers(rider)
    )

    assert response.status_code == 201
    async with AsyncSessionLocal() as session:
        assert await session.get(Ride, response.json()["id"]) is not None


async def test_concurrent_start_and_cancel_exactly_one_wins(live_client):
    """Four starts and four cancels hit the same ride at once.

    Both actions are valid from ``assigned``, so without the row lock several
    would read ``assigned`` and all "succeed" (lost updates). With it, exactly
    one wins and every other request sees the new status and gets 409.
    """
    (driver,), (rider,) = await seed(drivers=1, riders=1)
    created = await live_client.post(
        "/rides", json=PAYLOAD, headers=auth_headers(rider)
    )
    ride_id = created.json()["id"]
    async with AsyncSessionLocal() as session:
        driver_user = await session.get(User, driver.user_id)

    await warm_pool(live_client)

    starts = [
        live_client.post(f"/rides/{ride_id}/start", headers=auth_headers(driver_user))
        for _ in range(4)
    ]
    cancels = [
        live_client.post(f"/rides/{ride_id}/cancel", headers=auth_headers(rider))
        for _ in range(4)
    ]
    responses = await asyncio.gather(*starts, *cancels)

    codes = sorted(r.status_code for r in responses)
    assert codes == [200] + [409] * 7
    winner = next(r for r in responses if r.status_code == 200).json()
    async with AsyncSessionLocal() as session:
        ride = await session.get(Ride, ride_id)
        stored_driver = await session.get(Driver, driver.id)
    assert ride.status == winner["status"]
    # The driver's availability matches whichever action won.
    assert stored_driver.is_available is (winner["status"] == "cancelled")
