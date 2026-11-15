"""FastAPI dependencies: application context, current user and their book."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from picciuli import Book
from picciuli_api.auth import AuthenticationError, TokenVerifier, User
from picciuli_api.books import BookRegistry, ImportLimiter
from picciuli_api.config import Settings
from picciuli_api.providers import SharedProviders

__all__ = [
    "AppContext",
    "BookDep",
    "ContextDep",
    "UserDep",
    "bearer_scheme",
    "get_book",
    "get_context",
    "get_current_user",
]


@dataclass(frozen=True, slots=True)
class AppContext:
    """Long-lived services shared by every request."""

    settings: Settings
    verifier: TokenVerifier
    books: BookRegistry
    providers: SharedProviders
    imports: ImportLimiter


bearer_scheme = HTTPBearer(
    scheme_name="bearer",
    description="OpenID Connect access token (JWT) from the identity provider.",
    auto_error=False,
)


def get_context(request: Request) -> AppContext:
    """Return the services of the running application."""
    context = request.app.state.context
    if not isinstance(context, AppContext):
        raise RuntimeError("the application context is not configured")
    return context


ContextDep = Annotated[AppContext, Depends(get_context)]


def get_current_user(
    context: ContextDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(bearer_scheme)
    ],
) -> User:
    """Authenticate the request from its `Authorization: Bearer` header."""
    if credentials is None:
        raise AuthenticationError("missing bearer token")
    return context.verifier.verify(credentials.credentials)


UserDep = Annotated[User, Depends(get_current_user)]


def get_book(context: ContextDep, user: UserDep) -> Iterator[Book]:
    """Lease the current user's book for the duration of the request."""
    with context.books.lease(user.id) as book:
        yield book


BookDep = Annotated[Book, Depends(get_book)]
