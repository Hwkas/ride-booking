"""Map exceptions to HTTP responses with a single, consistent error body.

Every error leaves the API as::

    {"error": {"code": "...", "message": "...", "details": ...}}
"""

import logging

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    AppError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.schemas.error import ErrorDetail, ErrorResponse


logger = logging.getLogger(__name__)

# Most specific class wins: lookup walks the exception's MRO.
STATUS_BY_ERROR: dict[type[AppError], int] = {
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
}

# Shared OpenAPI entry so routes can document their error responses.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}


def status_for(exc: AppError) -> int:
    """Return the HTTP status for a domain error (400 if unmapped)."""
    for cls in type(exc).__mro__:
        if cls in STATUS_BY_ERROR:
            return STATUS_BY_ERROR[cls]
    return status.HTTP_400_BAD_REQUEST


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a JSON response in the standard error shape."""
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body, exclude_none=True),
        headers=headers,
    )


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Domain errors raised by services."""
    status_code = status_for(exc)
    headers = (
        {"WWW-Authenticate": "Bearer"}
        if status_code == status.HTTP_401_UNAUTHORIZED
        else None
    )
    return error_response(status_code, exc.code, exc.message, exc.details, headers)


async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Request body / query / path validation failures."""
    details = [
        {
            "field": ".".join(str(part) for part in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        "The request is invalid.",
        details,
    )


async def http_error_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Framework errors such as unknown routes (404) or wrong method (405)."""
    phrase = HTTPStatus(exc.status_code).phrase
    code = phrase.upper().replace(" ", "_").replace("-", "_")
    message = exc.detail if isinstance(exc.detail, str) else phrase
    return error_response(
        exc.status_code, code, message, headers=getattr(exc, "headers", None)
    )


async def integrity_error_handler(
    _request: Request, exc: IntegrityError
) -> JSONResponse:
    """Safety net for constraint violations a service did not translate."""
    logger.warning("Unhandled integrity error: %s", exc.orig)
    return error_response(
        status.HTTP_409_CONFLICT,
        ConflictError.code,
        ConflictError.default_message,
    )


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Anything unexpected: log it, never leak internals to the client."""
    logger.exception("Unhandled error", exc_info=exc)
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all handlers to the application."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(IntegrityError, integrity_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
