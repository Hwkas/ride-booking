from decimal import Decimal
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# The value shipped in .env.example: fine for local use, refused in production.
DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me-in-production"


class Settings(BaseSettings):
    """Application settings, loaded from env vars (and `.env` if present)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "Ride Booking API"
    environment: Literal["local", "test", "production"] = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: PostgresDsn
    test_database_url: PostgresDsn | None = None
    db_echo: bool = False

    # Auth
    # HS256 needs a key of at least 32 bytes (RFC 7518 §3.2).
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, gt=0)
    # bcrypt cost factor; 12 is a sensible production default, tests use 4.
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)

    # Fare
    fare_base: Decimal = Field(default=Decimal("2.50"), ge=0)
    fare_per_km: Decimal = Field(default=Decimal("1.20"), ge=0)

    # Admin seed
    admin_email: str | None = None
    admin_password: SecretStr | None = None

    @model_validator(mode="after")
    def _no_dev_secret_in_production(self) -> Self:
        if (
            self.environment == "production"
            and self.jwt_secret_key.get_secret_value() == DEV_JWT_SECRET
        ):
            raise ValueError("Set a real JWT_SECRET_KEY in production.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (use as a FastAPI dependency or directly)."""
    return Settings()
