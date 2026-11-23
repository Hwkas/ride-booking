"""Smoke tests for the test setup itself: DB wiring, isolation, migrations."""

import pytest

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import IntegrityError

from app.models import Base, RideStatus, User, UserRole
from tests.factories import create_driver, create_ride, create_user


async def test_health_reports_database_ok(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_runs_against_the_test_database(db_session):
    name = await db_session.scalar(text("SELECT current_database()"))

    assert name.endswith("_test")


async def test_migrations_match_models(db_session):
    def diff(sync_conn: Connection) -> list:
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(ctx, Base.metadata)

    conn = await db_session.connection()
    assert await conn.run_sync(diff) == []


async def test_factories_build_a_valid_ride_graph(db_session):
    ride = await create_ride(db_session, status=RideStatus.COMPLETED)

    assert ride.id is not None
    assert ride.final_fare == ride.fare_estimate
    assert ride.completed_at is not None


# The two tests below run in order: the first commits a user, the second
# proves the rollback removed it.
ISOLATION_EMAIL = "isolation-check@example.com"


async def test_isolation_writes_and_commits(db_session):
    await create_user(db_session, email=ISOLATION_EMAIL)
    await db_session.commit()  # releases the savepoint only

    count = await db_session.scalar(
        select(func.count()).where(User.email == ISOLATION_EMAIL)
    )
    assert count == 1


async def test_isolation_previous_test_left_no_data(db_session):
    count = await db_session.scalar(
        select(func.count()).where(User.email == ISOLATION_EMAIL)
    )
    assert count == 0


async def test_session_recovers_after_integrity_error(db_session):
    driver = await create_driver(db_session, available=False)
    await create_ride(db_session, driver=driver)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await create_ride(db_session, driver=driver)  # second active ride
    await db_session.rollback()  # back to the last savepoint, not the outer tx

    assert await db_session.scalar(select(func.count()).select_from(User)) >= 2
    rider = await create_user(db_session, role=UserRole.RIDER)
    assert rider.id is not None
