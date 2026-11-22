from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health check result."""

    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    version: str
