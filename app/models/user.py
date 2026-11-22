from sqlalchemy import String, true
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PrimaryKeyMixin, TimestampMixin, enum_column
from .enums import UserRole


class User(
    Base,
    PrimaryKeyMixin,
    TimestampMixin,
):
    """Anyone who can log in: rider, driver or admin."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(254),
        unique=True,
        nullable=False,  # stored lower-cased
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,  # bcrypt hash, never the raw password
    )

    full_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    role: Mapped[UserRole] = mapped_column(
        enum_column(UserRole, name="user_role"),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        default=True,
        server_default=true(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"User(id={self.id!r}, email={self.email!r}, role={self.role!r})"
