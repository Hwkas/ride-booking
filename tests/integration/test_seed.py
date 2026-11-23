"""Admin seed script (runs on the sync engine)."""

from collections.abc import Generator

import pytest

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import verify_password_sync
from app.db.session import sync_engine
from app.models import User, UserRole
from scripts import seed
from scripts.seed import SeedError, admin_credentials, ensure_admin


@pytest.fixture
def sync_session(engine) -> Generator[Session]:
    """Sync session in a rolled-back transaction (``engine`` builds the schema)."""
    with sync_engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


def settings_with(**overrides):
    return get_settings().model_copy(update=overrides)


# --- ensure_admin ---------------------------------------------------------------


def test_creates_admin_with_hashed_password(sync_session):
    admin, created = ensure_admin(sync_session, "boss@example.com", "Sup3r-secret")

    assert created is True
    assert admin.role is UserRole.ADMIN
    assert admin.is_active is True
    assert verify_password_sync("Sup3r-secret", admin.password_hash)


def test_is_idempotent_and_never_resets_password(sync_session):
    first, _ = ensure_admin(sync_session, "boss@example.com", "Sup3r-secret")

    again, created = ensure_admin(sync_session, "boss@example.com", "Different-pass")

    assert created is False
    assert again.id == first.id
    assert verify_password_sync("Sup3r-secret", again.password_hash)
    count = sync_session.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
    )
    assert count == 1


@pytest.mark.parametrize("role", [UserRole.RIDER, UserRole.DRIVER])
def test_refuses_to_promote_existing_user(sync_session, role):
    sync_session.add(
        User(email="taken@example.com", password_hash="x", full_name="T", role=role)
    )
    sync_session.flush()

    with pytest.raises(SeedError, match="refusing to promote"):
        ensure_admin(sync_session, "taken@example.com", "Sup3r-secret")


# --- admin_credentials ---------------------------------------------------------------


def test_credentials_are_normalised():
    settings = settings_with(
        admin_email="  Boss@Example.COM ", admin_password=SecretStr("Sup3r-secret")
    )

    assert admin_credentials(settings) == ("boss@example.com", "Sup3r-secret")


@pytest.mark.parametrize(
    "overrides",
    [{"admin_email": None}, {"admin_password": None}, {"admin_email": ""}],
)
def test_missing_credentials_skip_seeding(overrides):
    base = {"admin_email": "boss@example.com", "admin_password": SecretStr("x" * 8)}

    assert admin_credentials(settings_with(**(base | overrides))) is None


@pytest.mark.parametrize(
    ("email", "password"),
    [("not-an-email", "Sup3r-secret"), ("boss@example.com", "short")],
)
def test_invalid_credentials_are_rejected(email, password):
    settings = settings_with(admin_email=email, admin_password=SecretStr(password))

    with pytest.raises(SeedError, match="Invalid"):
        admin_credentials(settings)


def test_placeholder_password_refused_in_production_only():
    placeholder = SecretStr(seed.PLACEHOLDER_PASSWORD)
    prod = settings_with(
        environment="production", admin_email="a@b.io", admin_password=placeholder
    )
    local = settings_with(
        environment="local", admin_email="a@b.io", admin_password=placeholder
    )

    with pytest.raises(SeedError, match="placeholder"):
        admin_credentials(prod)
    assert admin_credentials(local) == ("a@b.io", seed.PLACEHOLDER_PASSWORD)


# --- main ---------------------------------------------------------------


def test_main_returns_error_code_on_seed_error(monkeypatch):
    def boom(_settings):
        raise SeedError("nope")

    monkeypatch.setattr(seed, "admin_credentials", boom)

    assert seed.main() == 1


def test_main_skips_when_not_configured(monkeypatch):
    monkeypatch.setattr(seed, "admin_credentials", lambda _settings: None)

    assert seed.main() == 0
