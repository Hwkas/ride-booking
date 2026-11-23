from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Machine-readable code plus a human message."""

    code: str = Field(examples=["NO_DRIVER_AVAILABLE"])
    message: str = Field(examples=["No driver is available right now."])
    details: Any | None = None


class ErrorResponse(BaseModel):
    """Body of every error response."""

    error: ErrorDetail
