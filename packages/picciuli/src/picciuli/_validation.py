"""Argument validation helpers (private).

They raise `ValidationError` for every malformed input, including wrong types,
so that API layers can map all input problems to a single error class.
"""

from __future__ import annotations

import datetime as dt
from typing import TypeVar

from picciuli.errors import ValidationError
from picciuli.limits import MAX_AMOUNT, MAX_ID, MAX_NAME_LENGTH, MAX_TEXT_LENGTH
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


def amount(value: object, field: str) -> int:
    """Validate an amount in minor units, at most `MAX_AMOUNT` in absolute value."""
    result = integer(value, field)
    if abs(result) > MAX_AMOUNT:
        raise ValidationError(f"{field} cannot exceed {MAX_AMOUNT} in absolute value")
    return result


def optional_amount(value: object, field: str) -> int | None:
    return None if value is None else amount(value, field)


def positive_amount(value: object, field: str) -> int:
    result = amount(value, field)
    if result <= 0:
        raise ValidationError(f"{field} must be greater than zero")
    return result


def non_negative_amount(value: object, field: str) -> int:
    result = amount(value, field)
    if result < 0:
        raise ValidationError(f"{field} cannot be negative")
    return result


def identifier(value: object, field: str) -> int:
    result = integer(value, field)
    if not 1 <= result <= MAX_ID:
        raise ValidationError(f"{field} must be between 1 and {MAX_ID}")
    return result


def count(value: object, field: str) -> int:
    """Validate a number of items, such as a limit or an offset."""
    result = integer(value, field)
    if result < 0:
        raise ValidationError(f"{field} cannot be negative")
    if result > MAX_ID:
        raise ValidationError(f"{field} cannot exceed {MAX_ID}")
    return result


def date(value: object, field: str) -> dt.date:
    if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
        raise ValidationError(f"{field} must be a datetime.date (without time)")
    return value


def optional_date(value: object, field: str) -> dt.date | None:
    return None if value is None else date(value, field)


def _max_length(text: str, field: str, max_length: int) -> str:
    if len(text) > max_length:
        raise ValidationError(f"{field} cannot exceed {max_length} characters")
    return text


def name(value: object, field: str, max_length: int = MAX_NAME_LENGTH) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    result = value.strip()
    if not result:
        raise ValidationError(f"{field} cannot be empty")
    if not result.isprintable():
        raise ValidationError(f"{field} must contain only printable characters")
    return _max_length(result, field, max_length)


def optional_text(
    value: object, field: str, max_length: int = MAX_TEXT_LENGTH
) -> str | None:
    """Strip text; empty or whitespace-only text becomes `None`."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string or None")
    result = value.strip()
    return _max_length(result, field, max_length) if result else None


def date_range(start: dt.date | None, end: dt.date | None) -> None:
    if start is not None and end is not None and start > end:
        raise ValidationError("start must be on or before end")


def position(value: object, upper: int, field: str = "position") -> int:
    result = integer(value, field)
    if not 1 <= result <= upper:
        raise ValidationError(f"{field} must be between 1 and {upper}")
    return result


def currency_code(value: object, field: str = "currency") -> str:
    """Validate an ISO 4217 style code: three ASCII letters, returned uppercase."""
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    result = value.strip().upper()
    if len(result) != 3 or not result.isascii() or not result.isalpha():
        raise ValidationError(f"{field} must be a three-letter code such as 'EUR'")
    return result


def isin(value: object) -> str | None:
    """Validate an ISIN (12 characters with a valid check digit) or `None`."""
    text = optional_text(value, "ISIN")
    if text is None:
        return None
    code = text.upper()
    if (
        len(code) != 12
        or not code.isascii()
        or not code[:2].isalpha()
        or not code[2:11].isalnum()
        or not code[11].isdigit()
    ):
        raise ValidationError(f"invalid ISIN {text!r}")
    digits = "".join(str(int(char, 36)) for char in code[:11])
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 0:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    if (10 - total % 10) % 10 != int(code[11]):
        raise ValidationError(f"invalid ISIN {text!r} (wrong check digit)")
    return code
