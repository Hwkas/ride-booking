from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    EmailStr,
    Field,
    StringConstraints,
)

from app.models.enums import UserRole


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _check_password_bytes(value: str) -> str:
    # bcrypt only uses the first 72 bytes; reject longer input instead of
    # silently ignoring the tail.
    if len(value.encode()) > 72:
        raise ValueError("Password must be at most 72 bytes.")
    return value


Email = Annotated[EmailStr, AfterValidator(_normalize_email)]
Password = Annotated[
    str,
    StringConstraints(min_length=8, max_length=72),
    AfterValidator(_check_password_bytes),
]


class RegisterRequest(BaseModel):
    """Self-service sign-up. Admin accounts are seeded, never self-registered."""

    email: Email = Field(examples=["rider@example.com"])
    password: Password = Field(examples=["S3cure-pass"])
    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ] = Field(examples=["Asha Rao"])
    role: Literal[UserRole.RIDER, UserRole.DRIVER] = Field(examples=["rider"])


class LoginRequest(BaseModel):
    """Email + password credentials."""

    email: Email = Field(examples=["rider@example.com"])
    # No length rules here: login must not reveal the password policy.
    password: str = Field(min_length=1, max_length=256, examples=["S3cure-pass"])


class TokenResponse(BaseModel):
    """Bearer access token."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Lifetime in seconds.", examples=[3600])
