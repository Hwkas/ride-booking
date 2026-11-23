from datetime import timedelta

import pytest

from fastapi import FastAPI
from sqlalchemy import select

from app.api.deps import AdminUser, DriverUser, RiderUser
from app.core.security import create_access_token
from app.models import User, UserRole
from tests.factories import DEFAULT_PASSWORD, auth_headers, create_user


def register_payload(**overrides):
    return {
        "email": "asha@example.com",
        "password": "S3cure-pass",
        "full_name": "Asha Rao",
        "role": "rider",
    } | overrides


# --- Register ----------------------------------------------------------------


@pytest.mark.parametrize("role", ["rider", "driver"])
async def test_register_creates_user(client, db_session, role):
    response = await client.post("/auth/register", json=register_payload(role=role))

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "asha@example.com"
    assert body["role"] == role
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body

    user = await db_session.scalar(select(User).where(User.id == body["id"]))
    assert user.password_hash != "S3cure-pass"  # stored hashed


async def test_register_normalises_email(client):
    response = await client.post(
        "/auth/register", json=register_payload(email="  Asha@Example.COM ")
    )

    assert response.status_code == 201
    assert response.json()["email"] == "asha@example.com"


async def test_register_duplicate_email_is_409(client):
    await client.post("/auth/register", json=register_payload())

    response = await client.post(
        "/auth/register", json=register_payload(email="ASHA@example.com")
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_cannot_self_register_as_admin(client):
    response = await client.post("/auth/register", json=register_payload(role="admin"))

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"email": "not-an-email"}, "body.email"),
        ({"password": "short"}, "body.password"),
        ({"password": "é" * 40}, "body.password"),  # 80 bytes > bcrypt's 72
        ({"full_name": "   "}, "body.full_name"),
        ({"role": "pilot"}, "body.role"),
    ],
)
async def test_register_validation(client, overrides, field):
    response = await client.post("/auth/register", json=register_payload(**overrides))

    assert response.status_code == 422
    fields = [d["field"] for d in response.json()["error"]["details"]]
    assert field in fields


# --- Login -------------------------------------------------------------------


async def test_login_returns_working_token(client):
    await client.post("/auth/register", json=register_payload())

    response = await client.post(
        "/auth/login", json={"email": "ASHA@example.com", "password": "S3cure-pass"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0

    me = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "asha@example.com"


async def test_login_wrong_password_is_401(client, db_session):
    user = await create_user(db_session)

    response = await client.post(
        "/auth/login", json={"email": user.email, "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_email_looks_like_wrong_password(client):
    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_disabled_account_is_401(client, db_session):
    user = await create_user(db_session, is_active=False)

    response = await client.post(
        "/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "This account is disabled."


# --- Current user / token handling -------------------------------------------


async def test_me_requires_token(client):
    response = await client.get("/users/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.parametrize(
    "header",
    ["Bearer not-a-jwt", "Basic dXNlcjpwYXNz", "Bearer"],
)
async def test_me_rejects_bad_authorization_header(client, header):
    response = await client.get("/users/me", headers={"Authorization": header})

    assert response.status_code == 401


async def test_me_rejects_expired_token(client, db_session):
    user = await create_user(db_session)
    token, _ = create_access_token(user.id, user.role, expires_delta=timedelta(-1))

    response = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Token has expired."


async def test_token_of_deleted_user_is_rejected(client, db_session):
    user = await create_user(db_session)
    headers = auth_headers(user)
    await db_session.delete(user)
    await db_session.flush()

    response = await client.get("/users/me", headers=headers)

    assert response.status_code == 401


async def test_disabling_account_revokes_existing_token(client, db_session):
    user = await create_user(db_session)
    headers = auth_headers(user)
    user.is_active = False
    await db_session.flush()

    response = await client.get("/users/me", headers=headers)

    assert response.status_code == 401


async def test_role_comes_from_database_not_token(client, db_session):
    rider = await create_user(db_session, role=UserRole.RIDER)
    forged_role_token, _ = create_access_token(rider.id, UserRole.ADMIN)

    response = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {forged_role_token}"}
    )

    assert response.json()["role"] == "rider"


# --- Role guards -------------------------------------------------------------


@pytest.fixture
def guarded_app(app: FastAPI):
    """Temporarily mount one route per role guard on the real app."""

    @app.get("/api/v1/_test/rider")
    async def rider_only(user: RiderUser) -> dict:
        return {"ok": user.role}

    @app.get("/api/v1/_test/driver")
    async def driver_only(user: DriverUser) -> dict:
        return {"ok": user.role}

    @app.get("/api/v1/_test/admin")
    async def admin_only(user: AdminUser) -> dict:
        return {"ok": user.role}

    added = app.router.routes[-3:]
    yield app
    for route in added:
        app.router.routes.remove(route)


@pytest.mark.parametrize("role", list(UserRole))
@pytest.mark.parametrize("guard", ["rider", "driver", "admin"])
async def test_role_guards(client, db_session, guarded_app, role, guard):
    user = await create_user(db_session, role=role)

    response = await client.get(f"/_test/{guard}", headers=auth_headers(user))

    if role.value == guard:
        assert response.status_code == 200
    else:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
