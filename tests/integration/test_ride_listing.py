"""GET /rides and GET /rides/{id}: visibility, filtering, pagination."""

import pytest

from app.models import RideStatus, UserRole
from tests.factories import auth_headers, create_driver, create_ride, create_user


@pytest.fixture
async def world(db_session):
    """Two riders, two drivers, an admin and rides between them.

    rider_a: 3 rides with driver_x (completed, cancelled, assigned)
    rider_b: 1 ride with driver_y (completed)
    """
    rider_a = await create_user(db_session, role=UserRole.RIDER)
    rider_b = await create_user(db_session, role=UserRole.RIDER)
    driver_x = await create_driver(db_session, available=False)
    driver_y = await create_driver(db_session, available=False)
    admin = await create_user(db_session, role=UserRole.ADMIN)

    a_rides = [
        await create_ride(db_session, rider=rider_a, driver=driver_x, status=s)
        for s in (RideStatus.COMPLETED, RideStatus.CANCELLED, RideStatus.ASSIGNED)
    ]
    b_ride = await create_ride(
        db_session, rider=rider_b, driver=driver_y, status=RideStatus.COMPLETED
    )
    driver_x_user = await db_session.get(type(rider_a), driver_x.user_id)
    driver_y_user = await db_session.get(type(rider_a), driver_y.user_id)
    return {
        "rider_a": rider_a,
        "rider_b": rider_b,
        "driver_x": driver_x_user,
        "driver_y": driver_y_user,
        "admin": admin,
        "a_rides": a_rides,
        "b_ride": b_ride,
    }


async def list_ids(client, user, **params) -> list[int]:
    response = await client.get("/rides", params=params, headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return [r["id"] for r in response.json()["items"]]


# --- Visibility ----------------------------------------------------------------


async def test_rider_sees_only_own_rides_newest_first(client, world):
    ids = await list_ids(client, world["rider_a"])

    assert ids == [r.id for r in reversed(world["a_rides"])]


async def test_driver_sees_only_rides_assigned_to_them(client, world):
    assert await list_ids(client, world["driver_y"]) == [world["b_ride"].id]
    assert sorted(await list_ids(client, world["driver_x"])) == sorted(
        r.id for r in world["a_rides"]
    )


async def test_admin_sees_all_rides(client, world):
    ids = await list_ids(client, world["admin"])

    assert sorted(ids) == sorted(
        [*(r.id for r in world["a_rides"]), world["b_ride"].id]
    )


async def test_driver_without_profile_sees_empty_list(client, db_session, world):
    newcomer = await create_user(db_session, role=UserRole.DRIVER)

    response = await client.get("/rides", headers=auth_headers(newcomer))

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_list_requires_auth(client):
    assert (await client.get("/rides")).status_code == 401


# --- Filtering & pagination -------------------------------------------------------


async def test_filter_by_single_status(client, world):
    ids = await list_ids(client, world["rider_a"], status="completed")

    assert ids == [world["a_rides"][0].id]


async def test_filter_by_several_statuses(client, world):
    response = await client.get(
        "/rides?status=completed&status=cancelled", headers=auth_headers(world["admin"])
    )

    statuses = {r["status"] for r in response.json()["items"]}
    assert statuses == {"completed", "cancelled"}
    assert response.json()["total"] == 3


async def test_unknown_status_is_422(client, world):
    response = await client.get(
        "/rides", params={"status": "pending"}, headers=auth_headers(world["admin"])
    )

    assert response.status_code == 422


async def test_pagination(client, world):
    headers = auth_headers(world["admin"])

    first = (await client.get("/rides", params={"limit": 3}, headers=headers)).json()
    second = (
        await client.get("/rides", params={"limit": 3, "offset": 3}, headers=headers)
    ).json()

    assert first["total"] == second["total"] == 4
    assert len(first["items"]) == 3
    assert len(second["items"]) == 1
    all_ids = [r["id"] for r in first["items"] + second["items"]]
    assert len(set(all_ids)) == 4  # no overlap, nothing skipped


async def test_items_have_full_ride_shape(client, world):
    response = await client.get("/rides", headers=auth_headers(world["rider_b"]))

    (ride,) = response.json()["items"]
    assert ride["status"] == "completed"
    assert ride["driver"]["id"] == world["b_ride"].driver_id
    assert ride["final_fare"] == ride["fare_estimate"]


# --- GET /rides/{id} ----------------------------------------------------------------


@pytest.mark.parametrize("who", ["rider_a", "driver_x", "admin"])
async def test_participants_and_admin_can_read_ride(client, world, who):
    ride = world["a_rides"][2]

    response = await client.get(f"/rides/{ride.id}", headers=auth_headers(world[who]))

    assert response.status_code == 200
    assert response.json()["id"] == ride.id
    assert response.json()["status"] == "assigned"


@pytest.mark.parametrize("who", ["rider_b", "driver_y"])
async def test_others_get_404(client, world, who):
    ride = world["a_rides"][0]

    response = await client.get(f"/rides/{ride.id}", headers=auth_headers(world[who]))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RIDE_NOT_FOUND"


async def test_unknown_ride_is_404(client, world):
    response = await client.get("/rides/999999", headers=auth_headers(world["admin"]))

    assert response.status_code == 404
