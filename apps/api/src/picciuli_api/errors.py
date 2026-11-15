"""Translation of exceptions into JSON error responses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from picciuli import (
    ConflictError,
    NotFoundError,
    PicciuliError,
    PriceProviderError,
    SchemaVersionError,
    ValidationError,
)
from picciuli_api.auth import AuthenticationError, AuthUnavailableError

__all__ = ["ERROR_RESPONSES", "ErrorResponse", "install_error_handlers"]


class ErrorResponse(BaseModel):
    """Body of every error response."""

    error: str = Field(examples=["not_found"])
    """Machine-readable error code."""
    detail: str = Field(examples=["account 42 not found"])
    """Human-readable explanation."""
    errors: list[dict[str, Any]] | None = None
    """Field-level problems of an invalid request, if any."""


# Most specific classes first: the first match wins.
_LIBRARY_ERRORS: Final[tuple[tuple[type[PicciuliError], int, str], ...]] = (
    (ValidationError, 422, "validation_error"),
    (NotFoundError, 404, "not_found"),
    (ConflictError, 409, "conflict"),
    (PriceProviderError, 502, "price_provider_error"),
    (SchemaVersionError, 500, "schema_version_error"),
    (PicciuliError, 500, "internal_error"),
)

_HTTP_CODES: Final = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "too_large",
}

ERROR_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid access token"},
    404: {"model": ErrorResponse, "description": "Entity not found"},
    409: {"model": ErrorResponse, "description": "Conflict with the stored data"},
    422: {"model": ErrorResponse, "description": "Invalid request or domain rule"},
}
"""Error responses documented on every authenticated endpoint."""


def _error(
    status: int,
    code: str,
    detail: str,
    *,
    errors: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=code, detail=detail, errors=errors)
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status, headers=headers
    )


async def _library_error(request: Request, exc: Exception) -> JSONResponse:
    cls, status, code = next(e for e in _LIBRARY_ERRORS if isinstance(exc, e[0]))
    detail = "internal error" if cls is PicciuliError else str(exc)
    return _error(status, code, detail)


async def _authentication_error(request: Request, exc: Exception) -> JSONResponse:
    return _error(
        401,
        "unauthorized",
        str(exc),
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


async def _auth_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return _error(503, "auth_unavailable", str(exc))


async def _request_validation(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise TypeError("unexpected exception type") from exc
    errors = jsonable_encoder(exc.errors(), exclude={"ctx", "url", "input"})
    return _error(422, "invalid_request", "the request is not valid", errors=errors)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise TypeError("unexpected exception type") from exc
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return _error(exc.status_code, code, str(exc.detail), headers=exc.headers)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    return _error(500, "internal_error", "internal error")


def install_error_handlers(app: FastAPI) -> None:
    """Register the JSON error handlers on `app`."""
    app.add_exception_handler(PicciuliError, _library_error)
    app.add_exception_handler(AuthenticationError, _authentication_error)
    app.add_exception_handler(AuthUnavailableError, _auth_unavailable)
    app.add_exception_handler(RequestValidationError, _request_validation)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    # Bugs still reach the server log: Starlette re-raises after responding.
    app.add_exception_handler(Exception, _unexpected_error)
