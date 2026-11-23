from datetime import timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models import UserRole


async def test_password_hash_round_trip():
    hashed = await hash_password("correct horse")

    assert hashed != "correct horse"
    assert await verify_password("correct horse", hashed)
    assert not await verify_password("wrong horse", hashed)


async def test_same_password_hashes_differently():
    assert await hash_password("same") != await hash_password("same")


async def test_verify_rejects_malformed_hash():
    assert not await verify_password("anything", "not-a-bcrypt-hash")


def test_token_round_trip():
    token, expires_in = create_access_token(7, UserRole.DRIVER)
    payload = decode_access_token(token)

    assert payload.user_id == 7
    assert payload.role is UserRole.DRIVER
    assert expires_in == get_settings().access_token_expire_minutes * 60


def test_expired_token_is_rejected():
    token, _ = create_access_token(1, UserRole.RIDER, expires_delta=timedelta(-1))

    with pytest.raises(AuthenticationError, match="expired"):
        decode_access_token(token)


def test_token_with_wrong_signature_is_rejected():
    token = jwt.encode(
        {"sub": "1", "role": "admin", "type": "access", "iat": 0, "exp": 9999999999},
        "someone-elses-secret-that-is-32-bytes-long",
        algorithm="HS256",
    )

    with pytest.raises(AuthenticationError, match="Invalid token"):
        decode_access_token(token)


def test_token_signed_with_none_algorithm_is_rejected():
    token = jwt.encode(
        {"sub": "1", "role": "admin", "type": "access", "iat": 0, "exp": 9999999999},
        key=None,
        algorithm="none",
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(token)


@pytest.mark.parametrize(
    "claims",
    [
        {"role": "rider", "type": "access"},  # no sub
        {"sub": "1", "role": "rider", "type": "refresh"},  # wrong type
        {"sub": "abc", "role": "rider", "type": "access"},  # non-numeric sub
        {"sub": "1", "role": "pilot", "type": "access"},  # unknown role
    ],
)
def test_malformed_claims_are_rejected(claims):
    settings = get_settings()
    token = jwt.encode(
        {"iat": 0, "exp": 9999999999, **claims},
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(token)


def test_garbage_token_is_rejected():
    with pytest.raises(AuthenticationError):
        decode_access_token("not.a.jwt")
