from fastapi import APIRouter, status

from app.api.deps import DbSession
from app.api.errors import error_responses
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserRead
from app.services.auth import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register as a rider or driver",
    responses=error_responses(409, 422),
)
async def register(data: RegisterRequest, session: DbSession) -> UserRead:
    """Create an account. Admin accounts cannot be self-registered."""
    user = await AuthService(session).register(data)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and receive a bearer token",
    responses=error_responses(401, 422),
)
async def login(data: LoginRequest, session: DbSession) -> TokenResponse:
    """Exchange email and password for a JWT access token."""
    return await AuthService(session).login(data)
