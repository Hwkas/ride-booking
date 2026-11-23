"""Health degradation, session helpers, lifespan and the seed entry point."""

from contextlib import contextmanager

import pytest

from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from app.api.v1 import health as health_module
from app.core.config import get_settings
from app.db import session as session_module
from app.main import lifespan
from app.models import Driver, Ride, User, UserRole
from scripts import seed


async def test_health_is_503_when_database_is_down(client, monkeypatch):
    async def down() -> bool:
        return False

    monkeypatch.setattr(health_module, "ping", down)

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "unavailable"


async def test_ping_returns_false_for_unreachable_database(monkeypatch):
    unreachable = create_async_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none",
        connect_args={"connect_timeout": 1},
    )
    monkeypatch.setattr(session_module, "async_engine", unreachable)

    assert await session_module.ping() is False
    await unreachable.dispose()


async def test_async_session_dependencies_work(engine):
    async for session in session_module.get_async_db():
        assert await session.scalar(text("SELECT 1")) == 1
    async for session in session_module.get_async_db_tx():
        assert await session.scalar(text("SELECT 1")) == 1


def test_sync_session_dependencies_work(engine):
    for session in session_module.get_sync_db():
        assert session.scalar(text("SELECT 1")) == 1
    for session in session_module.get_sync_db_tx():
        assert session.scalar(text("SELECT 1")) == 1


async def test_lifespan_disposes_engines_cleanly(engine):
    async with lifespan(FastAPI()):
        pass
    # Pools are recreated lazily, so the app keeps working afterwards.
    assert await session_module.ping() is True


def test_model_reprs_are_readable():
    user = User(email="a@b.io", password_hash="x", full_name="A", role=UserRole.RIDER)
    driver = Driver(user_id=1, vehicle_model="Prius", license_plate="AB123")

    assert "a@b.io" in repr(user)
    assert "AB123" in repr(driver)


def test_seed_main_creates_admin(engine, monkeypatch):
    settings = get_settings().model_copy(
        update={
            "admin_email": "Seeded@Example.com",
            "admin_password": SecretStr("Sup3r-secret"),
        }
    )
    monkeypatch.setattr(seed, "get_settings", lambda: settings)

    # Run main() inside a transaction that is rolled back afterwards.
    with session_module.sync_engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")

        @contextmanager
        def scope():
            with session.begin_nested():
                yield session

        try:
            assert seed.main(session_scope=scope) == 0
            admin = session.scalar(
                select(User).where(User.email == "seeded@example.com")
            )
            assert admin is not None
            assert admin.role is UserRole.ADMIN
        finally:
            session.close()
            outer.rollback()


@pytest.mark.parametrize("status", ["assigned", "completed"])
def test_ride_repr(status):
    ride = Ride(
        rider_id=1,
        driver_id=2,
        pickup_address="A",
        pickup_lat=0,
        pickup_lng=0,
        dropoff_address="B",
        dropoff_lat=1,
        dropoff_lng=1,
        distance_km=1,
        fare_estimate=1,
        status=status,
    )

    assert "rider_id=1" in repr(ride)
