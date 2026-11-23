"""Start / complete / cancel through the API."""

import pytest

from app.models import RideStatus, UserRole
from tests.factories import auth_headers, create_driver, create_ride, create_user


@pytest.fixture
async def rider(db_session):
    return await create_user(db_session, role=UserRole.RIDER)


@pytest.fixture
async def driver_user(db_session):
    return await create_user(db_session, role=UserRole.DRIVER)


@pytest.fixture
async def driver(db_session, driver_user):
    return await create_driver(db_session, user=driver_user, available=False)


@pytest.fixture
async def admin(db_session):
    return await create_user(db_session, role=UserRole.ADMIN)


async def make_ride(db_session, rider, driver, status=RideStatus.ASSIGNED):
    return await create_ride(db_session, rider=rider, driver=driver, status=status)


async def act(client, user, ride_id, action, json=None):
    return await client.post(
        f"/rides/{ride_id}/{action}", json=json, headers=auth_headers(user)
    )


# --- Start ----------------------------------------------------------------------


async def test_driver_starts_assigned_ride(
    client, db_session, rider, driver, driver_user
):
    ride = await make_ride(db_session, rider, driver)

    response = await act(client, driver_user, ride.id, "start")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["started_at"] is not None
    assert body["completed_at"] is None


# --- Complete -------------------------------------------------------------------


async def test_driver_completes_ride_sets_fare_and_frees_driver(
    client, db_session, rider, driver, driver_user
):
    ride = await make_ride(db_session, rider, driver, RideStatus.IN_PROGRESS)

    response = await act(client, driver_user, ride.id, "complete")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None
    assert body["final_fare"] == body["fare_estimate"]

    await db_session.refresh(driver)
    assert driver.is_available is True
    assert driver.available_since is not None


async def test_complete_before_start_is_409(
    client, db_session, rider, driver, driver_user
):
    ride = await make_ride(db_session, rider, driver)

    response = await act(client, driver_user, ride.id, "complete")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "INVALID_STATE_TRANSITION"
    assert error["details"] == {"status": "assigned", "action": "complete"}


async def test_completing_twice_is_409(client, db_session, rider, driver, driver_user):
    ride = await make_ride(db_session, rider, driver, RideStatus.IN_PROGRESS)
    assert (await act(client, driver_user, ride.id, "complete")).status_code == 200

    response = await act(client, driver_user, ride.id, "complete")

    assert response.status_code == 409


# --- Cancel ---------------------------------------------------------------------


@pytest.mark.parametrize("who", ["rider", "driver", "admin"])
async def test_cancel_assigned_ride(
    client, db_session, rider, driver, driver_user, admin, who
):
    ride = await make_ride(db_session, rider, driver)
    user = {"rider": rider, "driver": driver_user, "admin": admin}[who]

    response = await act(client, user, ride.id, "cancel", {"reason": " Plans changed "})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None
    assert body["cancellation_reason"] == "Plans changed"
    assert body["final_fare"] is None

    await db_session.refresh(driver)
    assert driver.is_available is True


async def test_cancel_without_body(client, db_session, rider, driver):
    ride = await make_ride(db_session, rider, driver)

    response = await act(client, rider, ride.id, "cancel")

    assert response.status_code == 200
    assert response.json()["cancellation_reason"] is None


async def test_cannot_cancel_after_pickup(
    client, db_session, rider, driver, driver_user
):
    ride = await make_ride(db_session, rider, driver, RideStatus.IN_PROGRESS)

    response = await act(client, rider, ride.id, "cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_cancel_reason_too_long_is_422(client, db_session, rider, driver):
    ride = await make_ride(db_session, rider, driver)

    response = await act(client, rider, ride.id, "cancel", {"reason": "x" * 256})

    assert response.status_code == 422


# --- Who may act ----------------------------------------------------------------


@pytest.mark.parametrize("action", ["start", "complete"])
async def test_rider_cannot_start_or_complete(
    client, db_session, rider, driver, action
):
    ride = await make_ride(db_session, rider, driver, RideStatus.IN_PROGRESS)

    response = await act(client, rider, ride.id, action)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.parametrize("action", ["start", "complete"])
async def test_admin_cannot_start_or_complete(
    client, db_session, rider, driver, admin, action
):
    ride = await make_ride(db_session, rider, driver)

    response = await act(client, admin, ride.id, action)

    assert response.status_code == 403


@pytest.mark.parametrize("action", ["start", "complete", "cancel"])
async def test_strangers_get_404_not_403(client, db_session, rider, driver, action):
    ride = await make_ride(db_session, rider, driver)
    other_rider = await create_user(db_session, role=UserRole.RIDER)
    other_driver = await create_driver(db_session)
    other_driver_user = await db_session.get(type(other_rider), other_driver.user_id)

    for stranger in (other_rider, other_driver_user):
        response = await act(client, stranger, ride.id, action)

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RIDE_NOT_FOUND"


async def test_unknown_ride_is_404(client, rider):
    response = await act(client, rider, 999_999, "cancel")

    assert response.status_code == 404


async def test_invalid_ride_id_is_422(client, rider):
    response = await act(client, rider, 0, "cancel")

    assert response.status_code == 422


async def test_lifecycle_requires_auth(client, db_session, rider, driver):
    ride = await make_ride(db_session, rider, driver)

    response = await client.post(f"/rides/{ride.id}/cancel")

    assert response.status_code == 401


# --- End to end -------------------------------------------------------------------


async def test_full_journey_driver_is_reused_afterwards(
    client, db_session, driver_user
):
    """Request -> start -> complete, then the same driver serves the next rider."""
    driver = await create_driver(db_session, user=driver_user, available=True)
    first, second = [await create_user(db_session) for _ in range(2)]
    payload = {
        "pickup": {"address": "A", "lat": 12.9756, "lng": 77.6059},
        "dropoff": {"address": "B", "lat": 12.9784, "lng": 77.6408},
    }

    created = await client.post("/rides", json=payload, headers=auth_headers(first))
    ride_id = created.json()["id"]
    assert created.json()["driver"]["id"] == driver.id

    # While busy, the driver cannot be assigned to anyone else.
    busy = await client.post("/rides", json=payload, headers=auth_headers(second))
    assert busy.json()["error"]["code"] == "NO_DRIVER_AVAILABLE"

    assert (await act(client, driver_user, ride_id, "start")).status_code == 200
    done = await act(client, driver_user, ride_id, "complete")
    assert done.json()["status"] == "completed"

    # Freed: the next rider gets the same driver, and the first can ride again.
    again = await client.post("/rides", json=payload, headers=auth_headers(second))
    assert again.status_code == 201
    assert again.json()["driver"]["id"] == driver.id


async def test_cancelled_rider_can_request_again(client, db_session, driver_user):
    await create_driver(db_session, user=driver_user, available=True)
    rider = await create_user(db_session)
    payload = {
        "pickup": {"address": "A", "lat": 12.9756, "lng": 77.6059},
        "dropoff": {"address": "B", "lat": 12.9784, "lng": 77.6408},
    }

    ride_id = (
        await client.post("/rides", json=payload, headers=auth_headers(rider))
    ).json()["id"]
    assert (await act(client, rider, ride_id, "cancel")).status_code == 200

    response = await client.post("/rides", json=payload, headers=auth_headers(rider))

    assert response.status_code == 201
