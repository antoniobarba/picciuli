"""The FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from starlette.routing import compile_path

import picciuli
from picciuli_api.auth import TokenVerifier
from picciuli_api.books import BookRegistry, ImportLimiter
from picciuli_api.config import Settings
from picciuli_api.deps import AppContext, get_current_user
from picciuli_api.errors import BODY_RESPONSES, ERROR_RESPONSES, install_error_handlers
from picciuli_api.login import create_login_router
from picciuli_api.providers import SharedProviders
from picciuli_api.routers import (
    accounts,
    categories,
    debts,
    investments,
    periods,
    schedules,
    securities,
    system,
    transactions,
)

__all__ = ["API_PREFIX", "create_app", "openapi_document"]

API_PREFIX = "/api/v1"

_DESCRIPTION = """\
REST API of [Picciuli](https://github.com/antoniobarba/picciuli), a personal
budgeting and money tracking engine.

Every user owns a private book: accounts, categories, transactions, periods,
budgets, securities and settings are never shared between users.

**Authentication.** Send an OpenID Connect access token (JWT) from the identity
provider in the `Authorization: Bearer <token>` header.

**Conventions.** Amounts are integers in minor units (cents) and signed from
your point of view (positive = money coming to you). Quantities, prices and
exchange rates are decimal strings. Dates are `YYYY-MM-DD`; ranges are
inclusive. `PATCH` bodies only change the fields they contain.

**Errors** always have the shape `{"error": "<code>", "detail": "<message>"}`.
"""

_TAGS: list[dict[str, Any]] = [
    {"name": "me", "description": "The authenticated user and their data."},
    {"name": "settings", "description": "Book-wide settings."},
    {"name": "accounts", "description": "Accounts, balances and registers."},
    {"name": "categories", "description": "The two-level category tree."},
    {"name": "transactions", "description": "Recording and searching money flows."},
    {
        "name": "schedules",
        "description": "Recurring transactions and catching up on them.",
    },
    {
        "name": "debts",
        "description": "Debt payoff forecasts, snowball and avalanche plans, "
        "loan payments.",
    },
    {"name": "periods", "description": "Named ranges of days and their summaries."},
    {"name": "budgets", "description": "Allowances per category and period."},
    {"name": "securities", "description": "Securities and their prices."},
    {"name": "exchange rates", "description": "Foreign currency rates."},
    {"name": "investments", "description": "Holdings, valuations, buying, selling."},
    {"name": "providers", "description": "Price and exchange-rate data sources."},
    {"name": "system", "description": "Service health."},
]


def create_app(
    settings: Settings | None = None,
    *,
    verifier: TokenVerifier | None = None,
    books: BookRegistry | None = None,
    providers: SharedProviders | None = None,
) -> FastAPI:
    """Build the ASGI application.

    Args:
        settings: Configuration; read from the environment if omitted.
        verifier: Access token verifier; by default it downloads the identity
            provider's keys from `settings.jwks_url`.
        books: Registry of the user databases; by default under
            `settings.users_dir`.
        providers: Shared price and rate providers; by default the registered
            ones, cached for `settings.price_cache_seconds`.
    """
    settings = settings or Settings()  # type: ignore[call-arg]
    context = AppContext(
        settings=settings,
        verifier=verifier
        or TokenVerifier.from_jwks_url(
            settings.jwks_url,
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            max_lifetime=settings.oidc_max_token_lifetime,
        ),
        books=books
        or BookRegistry(settings.users_dir, max_open=settings.max_open_books),
        providers=providers or SharedProviders(ttl=settings.price_cache_seconds),
        imports=ImportLimiter(settings.max_concurrent_imports),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        context.books.close()

    swagger_oauth: dict[str, Any] | None = None
    if settings.oidc_swagger_client_id:
        swagger_oauth = {
            "clientId": settings.oidc_swagger_client_id,
            "usePkceWithAuthorizationCodeGrant": True,
            "scopes": settings.oidc_swagger_scopes,
        }

    from picciuli_api import __version__

    app = FastAPI(
        title="Picciuli API",
        version=__version__,
        summary=f"Personal budgeting REST API (library {picciuli.__version__}).",
        description=_DESCRIPTION,
        openapi_tags=_TAGS,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        swagger_ui_init_oauth=swagger_oauth,
    )
    app.state.context = context
    install_error_handlers(app)
    if settings.login_origin:
        app.include_router(create_login_router(settings))

        @app.middleware("http")
        async def private_login_responses(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            response = await call_next(request)
            if request.url.path.startswith("/api/auth/"):
                response.headers["Cache-Control"] = "no-store"
                response.headers["Referrer-Policy"] = "no-referrer"
            return response

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            expose_headers=["Content-Disposition"],
            max_age=600,
        )

    @app.get("/healthz", tags=["system"])
    def health() -> dict[str, str]:
        """Liveness probe for containers and proxies. Needs no authentication."""
        return {"status": "ok"}

    api = APIRouter(
        prefix=API_PREFIX,
        dependencies=[Depends(get_current_user)],
        responses=ERROR_RESPONSES,
    )
    routers = (
        system.me,
        system.settings,
        accounts.router,
        categories.router,
        transactions.router,
        schedules.router,
        debts.router,
        periods.periods,
        periods.budgets,
        securities.securities,
        securities.rates,
        investments.router,
        system.providers,
    )
    for router in routers:
        api.include_router(router)
    app.include_router(api)
    app.state.route_methods = [
        (compile_path(API_PREFIX + route.path)[0], set(route.methods or ()))
        for router in routers
        for route in router.routes
        if isinstance(route, APIRoute)
    ]

    _document_body_errors(app)
    if settings.oidc_swagger_client_id:
        _add_oidc_scheme(app, settings.oidc_issuer)
    return app


def _document_body_errors(app: FastAPI) -> None:
    """Document `BODY_RESPONSES` on every operation that reads a request body."""
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = generate()
            error = {"$ref": "#/components/schemas/ErrorResponse"}
            for path_item in schema.get("paths", {}).values():
                for operation in path_item.values():
                    if "requestBody" not in operation:
                        continue
                    responses = operation.setdefault("responses", {})
                    for status, description in BODY_RESPONSES.items():
                        responses.setdefault(
                            str(status),
                            {
                                "description": description,
                                "content": {"application/json": {"schema": error}},
                            },
                        )
        return app.openapi_schema or generate()

    app.openapi = openapi  # type: ignore[method-assign]


def _add_oidc_scheme(app: FastAPI, issuer: str) -> None:
    """Let Swagger UI log in through the identity provider, besides pasted tokens."""
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = generate()
            schemes = schema.setdefault("components", {}).setdefault(
                "securitySchemes", {}
            )
            schemes["oidc"] = {
                "type": "openIdConnect",
                "openIdConnectUrl": (
                    f"{issuer.rstrip('/')}/.well-known/openid-configuration"
                ),
            }
            for path_item in schema.get("paths", {}).values():
                for operation in path_item.values():
                    security = operation.get("security")
                    if security and {"bearer": []} in security:
                        security.append({"oidc": []})
        if app.openapi_schema is None:
            raise RuntimeError("the OpenAPI schema was not generated")
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def openapi_document() -> dict[str, Any]:
    """Return the OpenAPI schema, independent of the local configuration."""
    settings = Settings(oidc_issuer="https://auth.example.com", oidc_audience="api")
    app = create_app(settings, books=BookRegistry(settings.users_dir))
    return app.openapi()
