"""Settings, providers and current-user endpoints."""

from __future__ import annotations

import contextlib
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from picciuli import Book, ImportSummary, SchemaVersionError, ValidationError
from picciuli.prices import available_providers
from picciuli.rates import available_rate_providers
from picciuli_api.deps import AppContext, BookDep, ContextDep, UserDep
from picciuli_api.errors import ErrorResponse
from picciuli_api.schemas.investments import ProviderOut, SecurityInfoOut
from picciuli_api.schemas.misc import ImportOut, MeOut, SettingsOut, SettingsUpdate

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


_SQLITE_MAGIC = b"SQLite format 3\x00"
_CHUNK = 1024 * 1024


@me.post(
    "/import",
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "A Picciuli database file, e.g. made by the TUI.",
            "content": {
                "application/vnd.sqlite3": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
    responses={413: {"model": ErrorResponse, "description": "The file is too big"}},
)
async def import_data(
    request: Request,
    user: UserDep,
    context: ContextDep,
    mode: Annotated[
        Literal["merge", "replace"],
        Query(description="Merge with your data, or replace it entirely."),
    ] = "merge",
) -> ImportOut:
    """Load the data of a Picciuli database file (SQLite) into your book.

    With `mode=merge`, accounts, categories, securities and periods with the
    same name (or ISIN, or days) are reused, and transactions identical to
    existing ones are skipped, so importing a file twice adds nothing.
    Merging requires the same currency and decimal digits. With
    `mode=replace`, all your data is deleted first and the file's settings
    are adopted. Either way the import is all-or-nothing.
    """
    limit = context.settings.max_import_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _too_big(limit)
    handle, name = tempfile.mkstemp(prefix="picciuli-import-", suffix=".db")
    path = Path(name)
    try:
        size = 0
        with os.fdopen(handle, "wb") as file:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise _too_big(limit)
                file.write(chunk)
        summary = await run_in_threadpool(
            _import_file, context, user.id, path, replace=mode == "replace"
        )
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
    return ImportOut.model_validate(summary)


def _too_big(limit: int) -> HTTPException:
    return HTTPException(
        413,
        f"the file is larger than {limit // (1024 * 1024) or 1} MB",
    )


def _import_file(
    context: AppContext, user_id: str, path: Path, *, replace: bool
) -> ImportSummary:
    with _open_upload(path) as source, context.books.lease(user_id) as book:
        return book.import_from(source, replace=replace)


def _open_upload(path: Path) -> Book:
    invalid = ValidationError("the file is not a Picciuli database")
    with path.open("rb") as file:
        if file.read(len(_SQLITE_MAGIC)) != _SQLITE_MAGIC:
            raise invalid
    try:
        with contextlib.closing(sqlite3.connect(path)) as db:
            check = db.execute("PRAGMA quick_check").fetchall()
            found = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
            ).fetchone()
    except sqlite3.DatabaseError:
        raise invalid from None
    if check != [("ok",)]:
        raise ValidationError("the database file is damaged")
    if found is None:
        raise invalid
    try:
        return Book.open(path, create=False)
    except SchemaVersionError as exc:
        raise ValidationError(f"cannot read the file: {exc}") from None
    except Exception:
        raise invalid from None
