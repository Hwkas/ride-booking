from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PrimaryKeyMixin, TimestampMixin, enum_column
from .driver import COORDINATE, Driver
from .enums import RideStatus
from .user import User


MONEY = Numeric(10, 2)

_ACTIVE = ", ".join(f"'{s.value}'" for s in RideStatus.active())


class Ride(
    Base,
    PrimaryKeyMixin,
    TimestampMixin,
):
    """A trip from pickup to dropoff; ``created_at`` is when it was requested."""

    __tablename__ = "rides"
    __table_args__ = (
        CheckConstraint("pickup_lat BETWEEN -90 AND 90", name="pickup_lat_range"),
        CheckConstraint("pickup_lng BETWEEN -180 AND 180", name="pickup_lng_range"),
        CheckConstraint("dropoff_lat BETWEEN -90 AND 90", name="dropoff_lat_range"),
        CheckConstraint("dropoff_lng BETWEEN -180 AND 180", name="dropoff_lng_range"),
        CheckConstraint("distance_km >= 0", name="distance_non_negative"),
        CheckConstraint("fare_estimate >= 0", name="fare_estimate_non_negative"),
        CheckConstraint(
            "final_fare IS NULL OR final_fare >= 0", name="final_fare_non_negative"
        ),
        # Lifecycle timestamps must match the status, so the data can't drift
        # from the state machine even if a bug slips past the service layer.
        CheckConstraint(
            "status <> 'in_progress' OR started_at IS NOT NULL",
            name="in_progress_has_started_at",
        ),
        CheckConstraint(
            "status <> 'completed' OR (started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND final_fare IS NOT NULL)",
            name="completed_has_fare_and_timestamps",
        ),
        CheckConstraint(
            "status <> 'cancelled' OR cancelled_at IS NOT NULL",
            name="cancelled_has_cancelled_at",
        ),
        # A driver can be on at most one active ride: the database is the final
        # guard against double assignment.
        Index(
            "uq_rides_driver_active",
            "driver_id",
            unique=True,
            postgresql_where=text(f"status IN ({_ACTIVE})"),
        ),
        # Likewise a rider can have at most one active ride (no booking every
        # free driver at once).
        Index(
            "uq_rides_rider_active",
            "rider_id",
            unique=True,
            postgresql_where=text(f"status IN ({_ACTIVE})"),
        ),
        # Driver history and earnings: filter by driver + status, range on time.
        Index(
            "ix_rides_driver_status_completed", "driver_id", "status", "completed_at"
        ),
        Index("ix_rides_rider_created", "rider_id", "created_at"),
    )

    rider_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT"),
        nullable=False,  # rides only exist once a driver is assigned
    )

    pickup_address: Mapped[str] = mapped_column(String(255), nullable=False)
    pickup_lat: Mapped[Decimal] = mapped_column(COORDINATE, nullable=False)
    pickup_lng: Mapped[Decimal] = mapped_column(COORDINATE, nullable=False)

    dropoff_address: Mapped[str] = mapped_column(String(255), nullable=False)
    dropoff_lat: Mapped[Decimal] = mapped_column(COORDINATE, nullable=False)
    dropoff_lng: Mapped[Decimal] = mapped_column(COORDINATE, nullable=False)

    distance_km: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    fare_estimate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    status: Mapped[RideStatus] = mapped_column(
        enum_column(RideStatus, name="ride_status"),
        default=RideStatus.ASSIGNED,
        nullable=False,
        index=True,
    )

    final_fare: Mapped[Decimal | None] = mapped_column(
        MONEY, default=None, nullable=True
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(
        String(255), default=None, nullable=True
    )

    # lazy="raise": async sessions can't lazy-load, so loading must be explicit.
    rider: Mapped[User] = relationship(init=False, repr=False, lazy="raise")
    driver: Mapped[Driver] = relationship(init=False, repr=False, lazy="raise")

    def __repr__(self) -> str:
        return (
            f"Ride(id={self.id!r}, status={self.status!r}, "
            f"rider_id={self.rider_id!r}, driver_id={self.driver_id!r})"
        )
