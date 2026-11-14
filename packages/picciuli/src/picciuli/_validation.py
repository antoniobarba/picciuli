"""Argument validation helpers (private).

They raise `ValidationError` for every malformed input, including wrong types,
so that API layers can map all input problems to a single error class.
"""

from __future__ import annotations

import datetime as dt
from typing import TypeVar

from picciuli.errors import ValidationError
from picciuli.model import Unset

T = TypeVar("T")


def is_set(value: T | Unset) -> bool:
    return not isinstance(value, Unset)


def integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer")
    return value


def optional_integer(value: object, field: str) -> int | None:
    return None if value is None else integer(value, field)


def positive_integer(value: object, field: str) -> int:
    result = integer(value, field)
    if result <= 0:
        raise ValidationError(f"{field} must be greater than zero")
    return result


def identifier(value: object, field: str) -> int:
    return integer(value, field)


def date(value: object, field: str) -> dt.date:
    if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
        raise ValidationError(f"{field} must be a datetime.date (without time)")
    return value


def optional_date(value: object, field: str) -> dt.date | None:
    return None if value is None else date(value, field)


def name(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    result = value.strip()
    if not result:
        raise ValidationError(f"{field} cannot be empty")
    if not result.isprintable():
        raise ValidationError(f"{field} must contain only printable characters")
    return result


def optional_text(value: object, field: str) -> str | None:
    """Strip text; empty or whitespace-only text becomes `None`."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string or None")
    return value.strip() or None


def date_range(start: dt.date | None, end: dt.date | None) -> None:
    if start is not None and end is not None and start > end:
        raise ValidationError("start must be on or before end")


def position(value: object, upper: int, field: str = "position") -> int:
    result = integer(value, field)
    if not 1 <= result <= upper:
        raise ValidationError(f"{field} must be between 1 and {upper}")
    return result
