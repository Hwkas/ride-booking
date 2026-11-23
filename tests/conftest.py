"""Shared test fixtures.

* Tests run against a separate Postgres database (``TEST_DATABASE_URL``); the
  dev database is never touched.
* The schema is built once per run with the real Alembic migrations, so the
  migrations themselves are exercised.
* Every test runs inside an outer transaction that is rolled back afterwards.
  The app's session dependencies are overridden to use that same session, so
  data created in a test (directly or through the API) never leaks into the
  next one, even when application code calls ``commit()``.
"""

import os

from collections.abc import AsyncGenerator

# --- Point the app at the test database BEFORE anything imports app.db ------
# app.db.session builds its engines at import time from settings, so the URL
# must be swapped first.
from app.core.config import get_settings


_settings = get_settings()
if _settings.test_database_url is None:
    raise RuntimeError("TEST_DATABASE_URL must be set to run the test suite.")
TEST_DATABASE_URL = str(_settings.test_database_url)
if str(_settings.database_url) == TEST_DATABASE_URL:
    raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL.")

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
get_settings.cache_clear()

# ruff: noqa: E402  (imports below depend on the environment set above)
import httpx
import pytest

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.db.session import get_async_db, get_async_db_tx
from app.main import create_app


def _reset_schema_and_migrate() -> None:
    """Drop everything in the test DB and rebuild it with Alembic."""
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine]:
    """Async engine on the freshly migrated test database."""
    _reset_schema_and_migrate()
    engine = create_async_engine(TEST_DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Session bound to an outer transaction that is rolled back after the test.

    ``create_savepoint`` makes the session's own commit/rollback operate on a
    SAVEPOINT, so application code can commit freely without ending the outer
    transaction.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """One application instance for the whole run."""
    return create_app()


@pytest.fixture
async def client(
    app: FastAPI, db_session: AsyncSession
) -> AsyncGenerator[httpx.AsyncClient]:
    """HTTP client whose requests share the test's rolled-back session."""

    async def _get_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def _get_db_tx() -> AsyncGenerator[AsyncSession]:
        # Mirrors get_async_db_tx: commit on success, roll back on error
        # (both at SAVEPOINT level here).
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_async_db] = _get_db
    app.dependency_overrides[get_async_db_tx] = _get_db_tx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test/api/v1"
    ) as client:
        yield client
    app.dependency_overrides.clear()
