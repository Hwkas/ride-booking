"""Domain exceptions.

Services raise these; they carry a stable machine-readable ``code`` and a human
message but know nothing about HTTP. The API layer maps them to status codes in
one place (``app.api.errors``).
"""

from typing import Any, ClassVar


class AppError(Exception):
    """Base class for all expected, client-facing errors."""

    code: ClassVar[str] = "APP_ERROR"
    default_message: ClassVar[str] = "Something went wrong."

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        """Create the error; ``details`` is optional structured context."""
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)


# --- 401 / 403 ---------------------------------------------------------------


class AuthenticationError(AppError):
    """Missing, invalid or expired credentials."""

    code = "NOT_AUTHENTICATED"
    default_message = "Could not validate credentials."


class InvalidCredentialsError(AuthenticationError):
    """Wrong email or password at login."""

    code = "INVALID_CREDENTIALS"
    default_message = "Incorrect email or password."


class PermissionDeniedError(AppError):
    """Authenticated, but not allowed to do this."""

    code = "PERMISSION_DENIED"
    default_message = "You do not have permission to perform this action."


# --- 404 ---------------------------------------------------------------------


class NotFoundError(AppError):
    """A requested resource does not exist (or is not visible to the caller)."""

    code = "NOT_FOUND"
    default_message = "Resource not found."


class DriverProfileNotFoundError(NotFoundError):
    """A driver user has not created their driver profile yet."""

    code = "DRIVER_PROFILE_NOT_FOUND"
    default_message = "Create your driver profile first."


class RideNotFoundError(NotFoundError):
    """The ride does not exist or is not visible to the caller."""

    code = "RIDE_NOT_FOUND"
    default_message = "Ride not found."


# --- 409 ---------------------------------------------------------------------


class ConflictError(AppError):
    """The request conflicts with the current state of the data."""

    code = "CONFLICT"
    default_message = "The request conflicts with existing data."


class EmailAlreadyRegisteredError(ConflictError):
    """Registration with an email that already has an account."""

    code = "EMAIL_ALREADY_REGISTERED"
    default_message = "An account with this email already exists."


class DriverProfileExistsError(ConflictError):
    """The driver already has a profile."""

    code = "DRIVER_PROFILE_EXISTS"
    default_message = "You already have a driver profile."


class LicensePlateTakenError(ConflictError):
    """Another driver is registered with this license plate."""

    code = "LICENSE_PLATE_TAKEN"
    default_message = "This license plate is already registered."


class InvalidStateTransitionError(ConflictError):
    """A ride cannot move from its current status to the requested one."""

    code = "INVALID_STATE_TRANSITION"
    default_message = "This action is not allowed in the ride's current status."


class NoDriverAvailableError(ConflictError):
    """No available driver could be assigned to a new ride."""

    code = "NO_DRIVER_AVAILABLE"
    default_message = "No driver is available right now. Please try again later."


class ActiveRideExistsError(ConflictError):
    """The rider (or driver) already has a ride in progress."""

    code = "ACTIVE_RIDE_EXISTS"
    default_message = "There is already an active ride."
