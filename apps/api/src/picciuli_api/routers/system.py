"""Settings, providers and current-user endpoints."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from picciuli.prices import available_providers
from picciuli.rates import available_rate_providers
from picciuli_api.deps import BookDep, ContextDep, UserDep
from picciuli_api.schemas.investments import ProviderOut, SecurityInfoOut
from picciuli_api.schemas.misc import MeOut, SettingsOut, SettingsUpdate

settings = APIRouter(prefix="/settings", tags=["settings"])
providers = APIRouter(prefix="/providers", tags=["providers"])
me = APIRouter(prefix="/me", tags=["me"])


@settings.get("")
def get_settings(book: BookDep) -> SettingsOut:
    """Book-wide settings: currency, cost method and providers."""
    return SettingsOut.model_validate(book.settings.get())


@settings.patch("")
def update_settings(book: BookDep, body: SettingsUpdate) -> SettingsOut:
    """Change some settings."""
    return SettingsOut.model_validate(book.settings.update(**body.changes()))


@providers.get("/prices")
def list_price_providers(user: UserDep) -> list[ProviderOut]:
    """Registered price providers."""
    return [ProviderOut.model_validate(p) for p in available_providers()]


@providers.get("/rates")
def list_rate_providers(user: UserDep) -> list[ProviderOut]:
    """Registered exchange-rate providers."""
    return [ProviderOut.model_validate(p) for p in available_rate_providers()]


@providers.get("/prices/{provider_id}/search")
def search_securities(
    user: UserDep,
    context: ContextDep,
    provider_id: str,
    q: Annotated[str, Query(min_length=1, description="Name, symbol or ISIN.")],
) -> list[SecurityInfoOut]:
    """Find instruments known to a price provider."""
    found = context.providers.prices(provider_id).search(q)
    return [SecurityInfoOut.model_validate(s) for s in found]


@me.get("")
def get_me(user: UserDep, book: BookDep) -> MeOut:
    """The authenticated user. The first call creates their (empty) book."""
    return MeOut(id=user.id, issuer=user.issuer, subject=user.subject)


@me.get(
    "/export",
    response_class=FileResponse,
    responses={200: {"content": {"application/vnd.sqlite3": {}}}},
)
def export_data(user: UserDep, context: ContextDep) -> FileResponse:
    """Download a copy of your database, usable with the Picciuli library or TUI."""
    handle, name = tempfile.mkstemp(prefix="picciuli-export-", suffix=".db")
    os.close(handle)
    path = Path(name)
    try:
        context.books.export(user.id, path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return FileResponse(
        path,
        media_type="application/vnd.sqlite3",
        filename="picciuli.db",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@me.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user: UserDep, context: ContextDep) -> None:
    """Delete all your data. The account at the identity provider is kept."""
    context.books.delete(user.id)
