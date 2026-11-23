from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)
from app.core.security import (
    burn_password_check,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


class AuthService:
    """Registration, login and token-to-user resolution."""

    def __init__(self, session: AsyncSession) -> None:
        """Create the service on the request's session."""
        self.session = session
        self.users = UserRepository(session)

    async def register(self, data: RegisterRequest) -> User:
        """Create a rider or driver account."""
        if await self.users.get_by_email(data.email) is not None:
            raise EmailAlreadyRegisteredError()

        user = User(
            email=data.email,
            password_hash=await hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
        )
        try:
            return await self.users.add(user)
        except IntegrityError as exc:
            # Lost a race with a concurrent registration of the same email.
            raise EmailAlreadyRegisteredError() from exc

    async def login(self, data: LoginRequest) -> TokenResponse:
        """Exchange valid credentials for an access token."""
        user = await self.users.get_by_email(data.email)
        if user is None:
            await burn_password_check()  # same timing as a wrong password
            raise InvalidCredentialsError()
        if not await verify_password(data.password, user.password_hash):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise AuthenticationError("This account is disabled.")

        token, expires_in = create_access_token(user.id, user.role)
        return TokenResponse(access_token=token, expires_in=expires_in)

    async def user_from_token(self, token: str) -> User:
        """Resolve a bearer token to an active user.

        The user is re-read from the database on every request, so disabling an
        account or changing a role takes effect immediately.
        """
        payload = decode_access_token(token)
        user = await self.users.get(payload.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError()
        return user
