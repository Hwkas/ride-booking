"""Password hashing and JWT access tokens."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import bcrypt
import jwt

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.models.enums import UserRole


ACCESS_TOKEN_TYPE = "access"


# --- Passwords ---------------------------------------------------------------
# bcrypt is deliberately slow (CPU-bound), so the async helpers run it in a
# worker thread instead of blocking the event loop.


def hash_password_sync(password: str) -> str:
    """Hash a password with bcrypt (blocking)."""
    salt = bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password_sync(password: str, password_hash: str) -> bool:
    """Check a password against a bcrypt hash (blocking)."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:  # malformed hash
        return False


async def hash_password(password: str) -> str:
    """Hash a password without blocking the event loop."""
    return await run_in_threadpool(hash_password_sync, password)


async def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password without blocking the event loop."""
    return await run_in_threadpool(verify_password_sync, password, password_hash)


@lru_cache
def _dummy_hash() -> str:
    return hash_password_sync("dummy-password-for-timing")


async def burn_password_check() -> None:
    """Spend the same time as a real check, so unknown emails aren't detectable."""
    await verify_password("not-the-password", _dummy_hash())


# --- Tokens ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Validated claims of an access token."""

    user_id: int
    role: UserRole
    expires_at: datetime


def create_access_token(
    user_id: int, role: UserRole, *, expires_delta: timedelta | None = None
) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)`` for the given user."""
    settings = get_settings()
    delta = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": role.value,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + delta,
    }
    token = jwt.encode(
        claims,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, int(delta.total_seconds())


def decode_access_token(token: str) -> TokenPayload:
    """Validate signature, expiry and shape; raise ``AuthenticationError`` if bad."""
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid token.") from exc

    if claims.get("type") != ACCESS_TOKEN_TYPE:
        raise AuthenticationError("Invalid token.")
    try:
        return TokenPayload(
            user_id=int(claims["sub"]),
            role=UserRole(claims["role"]),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid token.") from exc
