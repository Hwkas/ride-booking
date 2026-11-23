from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.api.errors import error_responses
from app.schemas.user import UserRead


router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserRead,
    summary="Current user's profile",
    responses=error_responses(401),
)
async def read_me(user: CurrentUser) -> UserRead:
    """Return the authenticated user."""
    return UserRead.model_validate(user)
