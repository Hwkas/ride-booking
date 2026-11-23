import pytest

from sqlalchemy import select

from app.models import Driver, RideStatus, UserRole
from tests.factories import auth_headers, create_driver, create_ride, create_user


@pytest.fixture
async def driver_user(db_session):
    return await create_user(db_session, role=UserRole.DRIVER)


@pytest.fixture
async def driver(db_session, driver_user):
    return await create_driver(db_session, user=driver_user, available=False)


def profile_payload(**overrides):
    return {
        "vehicle_model": "Toyota Prius",
        "license_plate": "ka-01 ab 1234",
    } | overrides


# --- POST /drivers/profile ---------------------------------------------------


async def test_create_profile(client, db_session, driver_user):
    response = await client.post(
        "/drivers/profile", json=profile_payload(), headers=auth_headers(driver_user)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == driver_user.id
    assert body["full_name"] == driver_user.full_name
    assert body["license_plate"] == "KA01AB1234"  # normalised
    assert body["is_available"] is False  # starts offline
    assert body["available_since"] is None
    assert body["current_lat"] is None

    stored = await db_session.scalar(
        select(Driver).where(Driver.user_id == driver_user.id)
    )
    assert stored.license_plate == "KA01AB1234"


async def test_create_profile_twice_is_409(client, driver, driver_user):
    response = await client.post(
        "/drivers/profile",
        json=profile_payload(license_plate="NEW123"),
        headers=auth_headers(driver_user),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DRIVER_PROFILE_EXISTS"


async def test_duplicate_plate_is_409_regardless_of_formatting(
    client, db_session, driver
):
    other = await create_user(db_session, role=UserRole.DRIVER)
    messy = f"{driver.license_plate[:3].lower()} - {driver.license_plate[3:]}"

    response = await client.post(
        "/drivers/profile",
        json=profile_payload(license_plate=messy),
        headers=auth_headers(other),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LICENSE_PLATE_TAKEN"


@pytest.mark.parametrize("role", [UserRole.RIDER, UserRole.ADMIN])
async def test_only_drivers_can_create_profile(client, db_session, role):
    user = await create_user(db_session, role=role)

    response = await client.post(
        "/drivers/profile", json=profile_payload(), headers=auth_headers(user)
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"license_plate": "A"}, "body.license_plate"),
        ({"license_plate": "KA#01"}, "body.license_plate"),
        ({"vehicle_model": "  "}, "body.vehicle_model"),
    ],
)
async def test_create_profile_validation(client, driver_user, overrides, field):
    response = await client.post(
        "/drivers/profile",
        json=profile_payload(**overrides),
        headers=auth_headers(driver_user),
    )

    assert response.status_code == 422
    assert field in [d["field"] for d in response.json()["error"]["details"]]


# --- GET /drivers/me -----------------------------------------------------------


async def test_read_my_profile(client, driver, driver_user):
    response = await client.get("/drivers/me", headers=auth_headers(driver_user))

    assert response.status_code == 200
    assert response.json()["id"] == driver.id


async def test_read_my_profile_before_creating_it_is_404(client, driver_user):
    response = await client.get("/drivers/me", headers=auth_headers(driver_user))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DRIVER_PROFILE_NOT_FOUND"


# --- PATCH /drivers/me/availability -------------------------------------------


async def test_go_online_with_location(client, driver, driver_user):
    response = await client.patch(
        "/drivers/me/availability",
        json={"is_available": True, "lat": 12.9716, "lng": 77.5946},
        headers=auth_headers(driver_user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_available"] is True
    assert body["available_since"] is not None
    assert body["current_lat"] == 12.9716
    assert body["current_lng"] == 77.5946


async def test_going_online_again_keeps_available_since(
    client, db_session, driver_user
):
    driver = await create_driver(db_session, user=driver_user, available=True)
    since = driver.available_since

    response = await client.patch(
        "/drivers/me/availability",
        json={"is_available": True, "lat": 1, "lng": 2},
        headers=auth_headers(driver_user),
    )

    assert response.status_code == 200
    assert driver.available_since == since  # idle time is not reset


async def test_go_offline_clears_available_since(client, db_session, driver_user):
    await create_driver(db_session, user=driver_user, available=True)

    response = await client.patch(
        "/drivers/me/availability",
        json={"is_available": False},
        headers=auth_headers(driver_user),
    )

    assert response.status_code == 200
    assert response.json()["is_available"] is False
    assert response.json()["available_since"] is None


async def test_coordinates_are_rounded_to_six_places(client, driver, driver_user):
    response = await client.patch(
        "/drivers/me/availability",
        json={"is_available": True, "lat": 12.12345678, "lng": -0.0000004},
        headers=auth_headers(driver_user),
    )

    assert response.json()["current_lat"] == 12.123457
    assert response.json()["current_lng"] == 0.0


async def test_cannot_go_online_during_active_ride(
    client, db_session, driver, driver_user
):
    await create_ride(db_session, driver=driver, status=RideStatus.IN_PROGRESS)

    response = await client.patch(
        "/drivers/me/availability",
        json={"is_available": True},
        headers=auth_headers(driver_user),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACTIVE_RIDE_EXISTS"


async def test_can_go_online_after_ride_completed(client, db_session, driver_user):
    driver = await create_driver(db_session, user=driver_user, available=False)
    await create_ride(db_session, driver=driver, status=RideStatus.COMPLETED)

    response = await client.patch(
        "/drivers/me/availability",
        json={"is_available": True},
        headers=auth_headers(driver_user),
    )

    assert response.status_code == 200
    assert response.json()["is_available"] is True


async def test_availability_without_profile_is_404(client, driver_user):
    response = await client.patch(
        "/drivers/me/availability",
        json={"is_available": True},
        headers=auth_headers(driver_user),
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"is_available": True, "lat": 12.9},  # lng missing
        {"is_available": True, "lat": 91, "lng": 0},
        {"is_available": True, "lat": 0, "lng": -181},
        {"lat": 1, "lng": 1},  # is_available missing
    ],
)
async def test_availability_validation(client, driver, driver_user, payload):
    response = await client.patch(
        "/drivers/me/availability", json=payload, headers=auth_headers(driver_user)
    )

    assert response.status_code == 422


# --- GET /drivers (admin) ------------------------------------------------------


@pytest.fixture
async def admin(db_session):
    return await create_user(db_session, role=UserRole.ADMIN)


async def test_admin_lists_drivers_with_filter_and_pagination(
    client, db_session, admin
):
    online = [await create_driver(db_session, available=True) for _ in range(3)]
    await create_driver(db_session, available=False)

    response = await client.get(
        "/drivers",
        params={"is_available": "true", "limit": 2, "offset": 0},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert all(d["is_available"] for d in body["items"])
    # newest first
    assert [d["id"] for d in body["items"]] == [online[2].id, online[1].id]

    second = await client.get(
        "/drivers",
        params={"is_available": "true", "limit": 2, "offset": 2},
        headers=auth_headers(admin),
    )
    assert [d["id"] for d in second.json()["items"]] == [online[0].id]


async def test_admin_lists_all_drivers_without_filter(client, db_session, admin):
    await create_driver(db_session, available=True)
    await create_driver(db_session, available=False)

    response = await client.get("/drivers", headers=auth_headers(admin))

    assert response.json()["total"] == 2


@pytest.mark.parametrize("role", [UserRole.RIDER, UserRole.DRIVER])
async def test_non_admin_cannot_list_drivers(client, db_session, role):
    user = await create_user(db_session, role=role)

    response = await client.get("/drivers", headers=auth_headers(user))

    assert response.status_code == 403


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_list_drivers_rejects_bad_pagination(client, admin, params):
    response = await client.get("/drivers", params=params, headers=auth_headers(admin))

    assert response.status_code == 422
