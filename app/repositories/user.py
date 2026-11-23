from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class UserRepository:
    """Data access for users (queries only, no business rules)."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def get(self, user_id: int) -> User | None:
        """Return the user with this id, if any."""
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with this (already normalised) email, if any."""
        return await self.session.scalar(select(User).where(User.email == email))

    async def add(self, user: User) -> User:
        """Insert a user and flush so the id is populated."""
        self.session.add(user)
        await self.session.flush()
        return user
