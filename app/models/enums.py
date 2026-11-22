from enum import StrEnum


class UserRole(StrEnum):
    """What a user is allowed to do."""

    RIDER = "rider"
    DRIVER = "driver"
    ADMIN = "admin"


class RideStatus(StrEnum):
    """Ride lifecycle; a ride is only created once a driver is assigned."""

    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    @classmethod
    def active(cls) -> tuple["RideStatus", ...]:
        """Statuses in which the driver is busy with the ride."""
        return (cls.ASSIGNED, cls.IN_PROGRESS)
