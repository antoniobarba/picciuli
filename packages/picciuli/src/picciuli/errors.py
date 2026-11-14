"""Exceptions raised by the Picciuli library.

Every error raised on purpose by the library derives from
[`PicciuliError`][picciuli.errors.PicciuliError], so callers can catch them all in
one place. Each subclass maps naturally to an HTTP status code for future web
backends:

| Exception            | Meaning                                   | HTTP |
|----------------------|-------------------------------------------|------|
| `ValidationError`    | The input is malformed or out of range    | 422  |
| `NotFoundError`      | A referenced entity does not exist        | 404  |
| `ConflictError`      | The operation conflicts with stored state | 409  |
| `SchemaVersionError` | The database file cannot be used          | 500  |
"""

from __future__ import annotations

__all__ = [
    "ConflictError",
    "NotFoundError",
    "PicciuliError",
    "SchemaVersionError",
    "ValidationError",
]


class PicciuliError(Exception):
    """Base class of all errors raised by the library."""


class ValidationError(PicciuliError, ValueError):
    """An argument has the wrong type, is out of range or breaks a domain rule.

    Examples include an empty name, a zero amount or unbalanced transaction splits.
    """


class NotFoundError(PicciuliError, LookupError):
    """A referenced entity (account, category, period, ...) does not exist."""


class ConflictError(PicciuliError):
    """The operation is valid on its own but conflicts with the stored data.

    Examples: a duplicate name, deleting a category that is still in use, or
    adding a transaction to a closed account.
    """


class SchemaVersionError(PicciuliError):
    """The database file is not a Picciuli database or has an unsupported version.

    It is raised when the file was created by a newer library version or by the
    legacy (v1) application, which must be converted with the migration tool.
    """
