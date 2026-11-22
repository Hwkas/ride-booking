from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, gt=0)

    # Fare
    fare_base: Decimal = Field(default=Decimal("2.50"), ge=0)
    fare_per_km: Decimal = Field(default=Decimal("1.20"), ge=0)

    # Admin seed
    admin_email: str | None = None
    admin_password: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (use as a FastAPI dependency or directly)."""
    return Settings()
