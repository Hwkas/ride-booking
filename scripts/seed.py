"""Create the admin account from ADMIN_EMAIL / ADMIN_PASSWORD (idempotent).

Admins cannot self-register through the API, so this is how the first one is
made. Safe to run on every deploy:

* admin missing        -> created
* admin already exists -> left untouched (the password is NOT reset)
* email used by a rider/driver -> refuses; it never promotes an account

Usage::

    python -m scripts.seed     (or: make seed)
"""

import logging
import sys

from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import hash_password_sync
from app.db.session import get_sync_db_tx
from app.models import User, UserRole
from app.schemas.auth import Email, Password


logger = logging.getLogger("seed")

PLACEHOLDER_PASSWORD = "change-me"


class SeedError(Exception):
    """The seed cannot proceed; the message says why."""


def admin_credentials(settings: Settings) -> tuple[str, str] | None:
    """Validated ``(email, password)`` from settings, or None if not configured."""
    if not settings.admin_email or settings.admin_password is None:
        return None
    password = settings.admin_password.get_secret_value()
    try:
        email = TypeAdapter(Email).validate_python(settings.admin_email)
        TypeAdapter(Password).validate_python(password)
    except ValidationError as exc:
        raise SeedError(f"Invalid ADMIN_EMAIL / ADMIN_PASSWORD: {exc}") from exc
    if settings.environment == "production" and password == PLACEHOLDER_PASSWORD:
        raise SeedError("Refusing the placeholder ADMIN_PASSWORD in production.")
    return email, password


def ensure_admin(session: Session, email: str, password: str) -> tuple[User, bool]:
    """Return ``(admin, created)``; create the admin if it does not exist yet."""
    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        if existing.role is not UserRole.ADMIN:
            raise SeedError(
                f"{email} already belongs to a {existing.role.value}; "
                "refusing to promote it to admin."
            )
        return existing, False

    admin = User(
        email=email,
        password_hash=hash_password_sync(password),
        full_name="Administrator",
        role=UserRole.ADMIN,
    )
    session.add(admin)
    session.flush()
    return admin, True


SessionScope = Callable[[], AbstractContextManager[Session]]

# Commit on success, roll back if anything raises.
default_session_scope: SessionScope = contextmanager(get_sync_db_tx)


def main(session_scope: SessionScope = default_session_scope) -> int:
    """Run the seed; return a process exit code.

    ``session_scope`` opens the transaction; tests pass their own.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [seed] %(message)s")
    try:
        credentials = admin_credentials(get_settings())
        if credentials is None:
            logger.info("ADMIN_EMAIL / ADMIN_PASSWORD not set; skipping admin seed.")
            return 0
        email, password = credentials
        with session_scope() as session:
            admin, created = ensure_admin(session, email, password)
            logger.info(
                "Admin %s %s.", admin.email, "created" if created else "already exists"
            )
    except SeedError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
