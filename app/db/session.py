from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


settings = get_settings()
DATABASE_URL = str(settings.database_url)


# Async Engine (API requests)
async_engine = create_async_engine(
    DATABASE_URL, echo=settings.db_echo, pool_pre_ping=True
)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)


async def get_async_db() -> AsyncGenerator[AsyncSession]:
    """Manage the AsyncSession lifecycle; no auto-commit.

    Commits are the caller's responsibility; uncommitted transactions are
    rolled back on close.
    """
    async with AsyncSessionLocal() as session:
        yield session


async def get_async_db_tx() -> AsyncGenerator[AsyncSession]:
    """Manage the AsyncSession lifecycle; commit on success, roll back on exception.

    One transaction per request via ``AsyncSessionLocal.begin()``.
    """
    async with AsyncSessionLocal.begin() as session:
        yield session


# Sync Engine (scripts / CLI, e.g. the seed script)
sync_engine = create_engine(DATABASE_URL, echo=settings.db_echo, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(
    bind=sync_engine, autocommit=False, autoflush=False, expire_on_commit=False
)


def get_sync_db() -> Generator[Session]:
    """Manage the sync Session lifecycle; no auto-commit.

    Commits are the caller's responsibility; uncommitted transactions are
    rolled back on close.
    """
    with SyncSessionLocal() as session:
        yield session


def get_sync_db_tx() -> Generator[Session]:
    """Manage the sync Session lifecycle; commit on success, roll back on exception.

    One transaction per request via ``session.begin()``. For scripts/CLI.
    """
    with SyncSessionLocal() as session, session.begin():
        yield session


async def ping() -> bool:
    """Return True if the database answers a trivial query."""
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
