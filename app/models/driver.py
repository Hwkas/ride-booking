from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PrimaryKeyMixin, TimestampMixin
from .user import User


# Six decimal places is ~0.1 m precision; plenty for pickup matching.
COORDINATE = Numeric(9, 6)


class Driver(
    Base,
    PrimaryKeyMixin,
    TimestampMixin,
):
    """Driver profile (vehicle + availability) for a user with the driver role."""

    __tablename__ = "drivers"
    __table_args__ = (
        CheckConstraint(
            "current_lat IS NULL OR current_lat BETWEEN -90 AND 90",
            name="current_lat_range",
        ),
        CheckConstraint(
            "current_lng IS NULL OR current_lng BETWEEN -180 AND 180",
            name="current_lng_range",
        ),
        # A location is either fully known or not at all.
        CheckConstraint(
            "(current_lat IS NULL) = (current_lng IS NULL)",
            name="current_location_complete",
        ),
        # Assignment only ever scans available drivers.
        Index(
            "ix_drivers_available",
            "available_since",
            postgresql_where="is_available",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,  # one driver profile per user
        nullable=False,
    )

    vehicle_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    license_plate: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,  # stored upper-cased, without spaces
    )

    is_available: Mapped[bool] = mapped_column(
        default=False,
        server_default=false(),
        nullable=False,
    )

    # When the driver last became free; the longest-idle driver is preferred
    # when distances are equal or unknown.
    available_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        nullable=True,
    )

    current_lat: Mapped[Decimal | None] = mapped_column(
        COORDINATE,
        default=None,
        nullable=True,
    )

    current_lng: Mapped[Decimal | None] = mapped_column(
        COORDINATE,
        default=None,
        nullable=True,
    )

    # lazy="raise": async sessions can't lazy-load, so loading must be explicit.
    user: Mapped[User] = relationship(init=False, repr=False, lazy="raise")

    def __repr__(self) -> str:
        return (
            f"Driver(id={self.id!r}, plate={self.license_plate!r}, "
            f"available={self.is_available!r})"
        )
