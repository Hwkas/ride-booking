import pytest

from pydantic import ValidationError

from app.core.config import DEV_JWT_SECRET, Settings


BASE = {"database_url": "postgresql+psycopg://u:p@localhost:5432/db"}


def make(**overrides) -> Settings:
    # _env_file=None: only the values given here, never the developer's .env
    return Settings(_env_file=None, **(BASE | overrides))


def test_short_jwt_secret_is_rejected():
    with pytest.raises(ValidationError, match="at least 32"):
        make(jwt_secret_key="change-me")


def test_dev_secret_is_fine_locally():
    settings = make(jwt_secret_key=DEV_JWT_SECRET, environment="local")

    assert settings.jwt_secret_key.get_secret_value() == DEV_JWT_SECRET


def test_dev_secret_is_refused_in_production():
    with pytest.raises(ValidationError, match="real JWT_SECRET_KEY"):
        make(jwt_secret_key=DEV_JWT_SECRET, environment="production")


def test_real_secret_is_accepted_in_production():
    settings = make(jwt_secret_key="x" * 64, environment="production")

    assert settings.environment == "production"


def test_env_example_ships_the_dev_secret():
    # Keeps .env.example and the production guard in sync.
    with open(".env.example") as f:
        assert f"JWT_SECRET_KEY={DEV_JWT_SECRET}\n" in f.read()
