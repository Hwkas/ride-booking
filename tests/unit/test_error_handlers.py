import httpx
import pytest

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.api.errors import register_exception_handlers, status_for
from app.core.exceptions import (
    ActiveRideExistsError,
    AppError,
    AuthenticationError,
    ConflictError,
    InvalidCredentialsError,
    InvalidStateTransitionError,
    NoDriverAvailableError,
    NotFoundError,
    PermissionDeniedError,
)


class Payload(BaseModel):
    name: str
    age: int


def build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise/not-found")
    async def not_found() -> None:
        raise NotFoundError("Ride 42 not found.")

    @app.get("/raise/transition")
    async def transition() -> None:
        raise InvalidStateTransitionError(
            "Cannot complete a ride in status assigned.",
            details={"from": "assigned", "to": "completed"},
        )

    @app.get("/raise/auth")
    async def auth() -> None:
        raise AuthenticationError()

    @app.get("/raise/integrity")
    async def integrity() -> None:
        raise IntegrityError("INSERT ...", {}, Exception("duplicate key"))

    @app.get("/raise/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.post("/validate")
    async def validate(payload: Payload) -> Payload:
        return payload

    return app


@pytest.fixture
async def client():
    # raise_app_exceptions=False: Starlette re-raises unhandled errors after the
    # 500 handler has responded; we only care about the response here.
    transport = httpx.ASGITransport(app=build_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (AuthenticationError(), 401),
        (InvalidCredentialsError(), 401),
        (PermissionDeniedError(), 403),
        (NotFoundError(), 404),
        (ConflictError(), 409),
        (InvalidStateTransitionError(), 409),
        (NoDriverAvailableError(), 409),
        (ActiveRideExistsError(), 409),
        (AppError(), 400),
    ],
)
def test_status_mapping_follows_class_hierarchy(exc: AppError, expected: int):
    assert status_for(exc) == expected


async def test_domain_error_uses_standard_body(client):
    response = await client.get("/raise/not-found")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Ride 42 not found."}
    }


async def test_domain_error_includes_details(client):
    response = await client.get("/raise/transition")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "INVALID_STATE_TRANSITION",
        "message": "Cannot complete a ride in status assigned.",
        "details": {"from": "assigned", "to": "completed"},
    }


async def test_authentication_error_sets_www_authenticate(client):
    response = await client.get("/raise/auth")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_validation_error_lists_fields(client):
    response = await client.post("/validate", json={"age": "not-a-number"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    fields = {d["field"] for d in error["details"]}
    assert fields == {"body.name", "body.age"}


async def test_unknown_route_uses_standard_body(client):
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found"}}


async def test_wrong_method_uses_standard_body(client):
    response = await client.delete("/raise/not-found")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_untranslated_integrity_error_becomes_409(client):
    response = await client.get("/raise/integrity")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert "duplicate key" not in response.text


async def test_unexpected_error_is_500_without_leaking_details(client):
    response = await client.get("/raise/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
        }
    }
    assert "secret" not in response.text
