"""GET /drivers/me/rides and GET /drivers/me/earnings."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import RideStatus, User, UserRole
from tests.factories import auth_headers, create_driver, create_ride, create_user


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# (completed_at, final_fare) for the driver's completed rides.
COMPLETED = [
    (utc(2026, 11, 2, 10, 0), "10.00"),
    (utc(2026, 11, 2, 23, 30), "5.50"),  # late on the 2nd
    (utc(2026, 11, 3, 0, 15), "7.25"),  # just after midnight: the 3rd
    (utc(2026, 11, 10, 9, 0), "12.00"),  # following week
    (utc(2026, 12, 1, 8, 0), "20.00"),  # following month
]


@pytest.fixture
async def setup(db_session):
    """One driver with 5 completed, 1 cancelled and 1 active ride, plus noise."""
    driver_user = await create_user(db_session, role=UserRole.DRIVER)
    driver = await create_driver(db_session, user=driver_user, available=False)

    completed = []
    for completed_at, fare in COMPLETED:
        ride = await create_ride(
            db_session,
            driver=driver,
            status=RideStatus.COMPLETED,
            created_at=completed_at - timedelta(minutes=30),
            started_at=completed_at - timedelta(minutes=20),
            completed_at=completed_at,
            fare_estimate=Decimal(fare),
            final_fare=Decimal(fare),
        )
        completed.append(ride)

    cancelled = await create_ride(
        db_session,
        driver=driver,
        status=RideStatus.CANCELLED,
        created_at=utc(2026, 11, 5, 12, 0),
        cancelled_at=utc(2026, 11, 5, 12, 5),
        fare_estimate=Decimal("99.00"),
    )
    active = await create_ride(
        db_session,
        driver=driver,
        status=RideStatus.ASSIGNED,
        created_at=utc(2026, 12, 2, 9, 0),
    )
    # Another driver's earnings must never leak in.
    await create_ride(
        db_session,
        status=RideStatus.COMPLETED,
        completed_at=utc(2026, 11, 2, 11, 0),
        final_fare=Decimal("500.00"),
    )
    return {
        "user": driver_user,
        "completed": completed,
        "cancelled": cancelled,
        "active": active,
    }


async def get(client, user, path, **params):
    return await client.get(path, params=params, headers=auth_headers(user))


# --- Earnings -----------------------------------------------------------------


async def test_all_time_earnings(client, setup):
    response = await get(client, setup["user"], "/drivers/me/earnings")

    assert response.status_code == 200
    assert response.json() == {
        "from": None,
        "to": None,
        "group_by": None,
        "total_earnings": "54.75",  # cancelled ride and other driver excluded
        "completed_rides": 5,
        "average_fare": "10.95",
        "breakdown": None,
    }


async def test_earnings_in_range_with_daily_breakdown(client, setup):
    response = await get(
        client,
        setup["user"],
        "/drivers/me/earnings",
        **{"from": "2026-11-01", "to": "2026-11-30", "group_by": "day"},
    )

    body = response.json()
    assert body["from"] == "2026-11-01"
    assert body["to"] == "2026-11-30"
    assert body["total_earnings"] == "34.75"
    assert body["completed_rides"] == 4
    assert body["average_fare"] == "8.69"  # 34.75 / 4 = 8.6875, rounded half-up
    assert body["breakdown"] == [
        {"period": "2026-11-02", "earnings": "15.50", "rides": 2},
        {"period": "2026-11-03", "earnings": "7.25", "rides": 1},
        {"period": "2026-11-10", "earnings": "12.00", "rides": 1},
    ]


async def test_weekly_breakdown_starts_on_monday(client, setup):
    response = await get(client, setup["user"], "/drivers/me/earnings", group_by="week")

    def monday(d: date) -> str:
        return (d - timedelta(days=d.weekday())).isoformat()

    expected: dict[str, tuple[Decimal, int]] = {}
    for completed_at, fare in COMPLETED:
        week = monday(completed_at.date())
        total, rides = expected.get(week, (Decimal(0), 0))
        expected[week] = (total + Decimal(fare), rides + 1)

    assert response.json()["breakdown"] == [
        {"period": week, "earnings": f"{total:.2f}", "rides": rides}
        for week, (total, rides) in sorted(expected.items())
    ]


async def test_monthly_breakdown(client, setup):
    response = await get(
        client, setup["user"], "/drivers/me/earnings", group_by="month"
    )

    assert response.json()["breakdown"] == [
        {"period": "2026-11-01", "earnings": "34.75", "rides": 4},
        {"period": "2026-12-01", "earnings": "20.00", "rides": 1},
    ]


async def test_single_day_range_is_inclusive_and_bounded_at_midnight(client, setup):
    response = await get(
        client,
        setup["user"],
        "/drivers/me/earnings",
        **{"from": "2026-11-02", "to": "2026-11-02"},
    )

    body = response.json()
    assert body["total_earnings"] == "15.50"  # 23:30 in, 00:15 next day out
    assert body["completed_rides"] == 2


async def test_open_ended_range(client, setup):
    response = await get(
        client, setup["user"], "/drivers/me/earnings", **{"from": "2026-11-10"}
    )

    assert response.json()["total_earnings"] == "32.00"
    assert response.json()["completed_rides"] == 2


async def test_empty_range_returns_zeros(client, setup):
    response = await get(
        client,
        setup["user"],
        "/drivers/me/earnings",
        **{"from": "2025-01-01", "to": "2025-01-31", "group_by": "day"},
    )

    body = response.json()
    assert body["total_earnings"] == "0.00"
    assert body["completed_rides"] == 0
    assert body["average_fare"] == "0.00"
    assert body["breakdown"] == []


async def test_new_driver_has_zero_earnings(client, db_session):
    user = await create_user(db_session, role=UserRole.DRIVER)
    await create_driver(db_session, user=user)

    response = await get(client, user, "/drivers/me/earnings")

    assert response.json()["total_earnings"] == "0.00"


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-11-30", "to": "2026-11-01"},  # reversed
        {"from": "not-a-date"},
        {"group_by": "year"},
    ],
)
async def test_earnings_validation(client, setup, params):
    response = await get(client, setup["user"], "/drivers/me/earnings", **params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- Ride history ---------------------------------------------------------------


async def test_history_lists_every_ride_newest_first(client, setup):
    response = await get(client, setup["user"], "/drivers/me/rides", limit=100)

    body = response.json()
    assert body["total"] == 7  # 5 completed + cancelled + active, not the other's
    ids = [r["id"] for r in body["items"]]
    assert ids[0] == setup["active"].id  # requested most recently
    assert setup["cancelled"].id in ids


async def test_history_status_filter(client, setup):
    response = await get(client, setup["user"], "/drivers/me/rides", status="cancelled")

    assert [r["id"] for r in response.json()["items"]] == [setup["cancelled"].id]


async def test_history_date_filter_uses_request_time(client, setup):
    response = await get(
        client,
        setup["user"],
        "/drivers/me/rides",
        **{"from": "2026-11-02", "to": "2026-11-05"},
    )

    ids = {r["id"] for r in response.json()["items"]}
    expected = {r.id for r in setup["completed"][:3]} | {setup["cancelled"].id}
    assert ids == expected


async def test_history_pagination(client, setup):
    response = await get(client, setup["user"], "/drivers/me/rides", limit=2, offset=6)

    assert response.json()["total"] == 7
    assert len(response.json()["items"]) == 1


# --- Access -------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/drivers/me/rides", "/drivers/me/earnings"])
async def test_driver_without_profile_is_404(client, db_session, path):
    user = await create_user(db_session, role=UserRole.DRIVER)

    response = await get(client, user, path)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DRIVER_PROFILE_NOT_FOUND"


@pytest.mark.parametrize("role", [UserRole.RIDER, UserRole.ADMIN])
@pytest.mark.parametrize("path", ["/drivers/me/rides", "/drivers/me/earnings"])
async def test_non_drivers_get_403(client, db_session, role, path):
    user: User = await create_user(db_session, role=role)

    response = await get(client, user, path)

    assert response.status_code == 403
