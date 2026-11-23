"""Shared FastAPI dependencies: database session, current user, role guards."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.db.session import get_async_db_tx
from app.models import User, UserRole
from app.services.auth import AuthService


# One transaction per request: committed on success, rolled back on error.
# scope="function" commits BEFORE the response is sent, so a failed commit
# becomes an error response instead of a false success.
DbSession = Annotated[AsyncSession, Depends(get_async_db_tx, scope="function")]

# auto_error=False: missing credentials go through our own 401 error shape.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT from /auth/login")


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Return the authenticated, active user or raise 401."""
    if credentials is None:
        raise AuthenticationError("Not authenticated.")
    return await AuthService(session).user_from_token(credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[User]]:
    """Dependency factory: allow only users with one of ``roles`` (else 403)."""
    allowed = frozenset(roles)

    async def _guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDeniedError()
        return user

    return _guard


RiderUser = Annotated[User, Depends(require_roles(UserRole.RIDER))]
DriverUser = Annotated[User, Depends(require_roles(UserRole.DRIVER))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
