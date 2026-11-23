"""The database constraints are the last line of defence against races.

Each service checks a rule first ("is this email taken?") and then relies on a
unique constraint if a concurrent request slips in between the check and the
insert. These tests disable the pre-check, so the insert really hits the
constraint, and assert that the violation still becomes the right 409 (and
that the constraint names hard-coded in the services match the database).
"""

from app.models import RideStatus, UserRole
from app.repositories.driver import DriverRepository
from app.repositories.ride import RideRepository
from app.repositories.user import UserRepository
from tests.factories import auth_headers, create_driver, create_ride, create_user


async def _none(*_args, **_kwargs):
    return None


async def _false(*_args, **_kwargs):
    return False


async def test_register_race_on_email(client, db_session, monkeypatch):
    existing = await create_user(db_session)
    monkeypatch.setattr(UserRepository, "get_by_email", _none)

    response = await client.post(
        "/auth/register",
        json={
            "email": existing.email,
            "password": "S3cure-pass",
            "full_name": "Dup",
            "role": "rider",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_driver_profile_race_on_plate(client, db_session, monkeypatch):
    taken = await create_driver(db_session)
    newcomer = await create_user(db_session, role=UserRole.DRIVER)
    monkeypatch.setattr(DriverRepository, "plate_exists", _false)

    response = await client.post(
        "/drivers/profile",
        json={"vehicle_model": "Civic", "license_plate": taken.license_plate},
        headers=auth_headers(newcomer),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LICENSE_PLATE_TAKEN"


async def test_driver_profile_race_on_second_profile(client, db_session, monkeypatch):
    user = await create_user(db_session, role=UserRole.DRIVER)
    await create_driver(db_session, user=user)
    monkeypatch.setattr(DriverRepository, "get_by_user_id", _none)

    response = await client.post(
        "/drivers/profile",
        json={"vehicle_model": "Civic", "license_plate": "FRESH123"},
        headers=auth_headers(user),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DRIVER_PROFILE_EXISTS"


async def test_ride_request_race_on_rider_active_ride(client, db_session, monkeypatch):
    rider = await create_user(db_session)
    await create_ride(db_session, rider=rider, status=RideStatus.ASSIGNED)
    await create_driver(db_session)
    monkeypatch.setattr(RideRepository, "rider_has_active_ride", _false)

    response = await client.post(
        "/rides",
        json={
            "pickup": {"address": "A", "lat": 12.97, "lng": 77.59},
            "dropoff": {"address": "B", "lat": 12.98, "lng": 77.64},
        },
        headers=auth_headers(rider),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACTIVE_RIDE_EXISTS"


async def test_ride_request_driver_flagged_available_but_busy(client, db_session):
    """Inconsistent data (available flag set while on a ride) cannot double-book."""
    driver = await create_driver(db_session, available=True)
    await create_ride(db_session, driver=driver, status=RideStatus.IN_PROGRESS)
    rider = await create_user(db_session)

    response = await client.post(
        "/rides",
        json={
            "pickup": {"address": "A", "lat": 12.97, "lng": 77.59},
            "dropoff": {"address": "B", "lat": 12.98, "lng": 77.64},
        },
        headers=auth_headers(rider),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DRIVER_AVAILABLE"
