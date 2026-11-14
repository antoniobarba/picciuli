"""Conversion between minor-unit integers and human-readable amounts.

The library stores every amount as an `int` number of minor units (for example
cents). These helpers are shared by all user interfaces so that parsing and
formatting rules are consistent everywhere.

Example:
    >>> from picciuli.money import format_amount, parse_amount
    >>> parse_amount("-1,234.5")
    -123450
    >>> format_amount(-123450, currency="€")
    '-€1,234.50'
    >>> format_amount(123450, decimal_separator=",", group_separator=".")
    '1.234,50'
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from picciuli.errors import ValidationError

__all__ = ["format_amount", "from_decimal", "parse_amount", "to_decimal"]

_MAX_DIGITS = 6


def _check_digits(digits: int) -> None:
    if isinstance(digits, bool) or not isinstance(digits, int):
        raise ValidationError("digits must be an integer")
    if not 0 <= digits <= _MAX_DIGITS:
        raise ValidationError(f"digits must be between 0 and {_MAX_DIGITS}")


def to_decimal(amount: int, *, digits: int = 2) -> Decimal:
    """Convert minor units to a `Decimal` in major units.

    Args:
        amount: Amount in minor units.
        digits: Number of minor-unit digits of the currency.

    Returns:
        The exact decimal value, for example `Decimal("12.34")` for `1234`.

    Raises:
        ValidationError: If `amount` is not an integer or `digits` is invalid.
    """
    _check_digits(digits)
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValidationError("amount must be an integer")
    return Decimal(amount).scaleb(-digits)


def from_decimal(value: Decimal, *, digits: int = 2) -> int:
    """Convert a `Decimal` in major units to minor units without rounding.

    Args:
        value: Amount in major units, for example `Decimal("12.34")`.
        digits: Number of minor-unit digits of the currency.

    Returns:
        The amount in minor units.

    Raises:
        ValidationError: If the value is not finite or has more decimal digits
            than the currency allows.
    """
    _check_digits(digits)
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValidationError("amount must be a finite decimal number")
    scaled = value.scaleb(digits)
    if scaled != scaled.to_integral_value():
        raise ValidationError(f"amount cannot have more than {digits} decimal digits")
    return int(scaled)


def parse_amount(
    text: str,
    *,
    digits: int = 2,
    decimal_separator: str = ".",
    group_separator: str | None = ",",
) -> int:
    """Parse a human-entered amount into minor units.

    Leading and trailing spaces, a leading `+` or `-` sign and group separators
    are accepted. No rounding is performed.

    Args:
        text: Text such as `"1,234.56"` or `"-12"`.
        digits: Number of minor-unit digits of the currency.
        decimal_separator: Character separating the decimal digits.
        group_separator: Thousands separator to ignore, or `None` to reject any.

    Returns:
        The amount in minor units.

    Raises:
        ValidationError: If the text is not a valid amount.
    """
    if not isinstance(text, str):
        raise ValidationError("amount must be a string")
    if decimal_separator == group_separator:
        raise ValidationError("decimal and group separators must differ")
    cleaned = text.strip()
    if group_separator:
        cleaned = cleaned.replace(group_separator, "")
    cleaned = cleaned.replace(decimal_separator, ".")
    body = cleaned.lstrip("+-")
    if not body or len(cleaned) - len(body) > 1:
        raise ValidationError(f"invalid amount: {text!r}")
    if not all(ch in "0123456789." for ch in body) or body.count(".") > 1:
        raise ValidationError(f"invalid amount: {text!r}")
    if body == ".":
        raise ValidationError(f"invalid amount: {text!r}")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:  # pragma: no cover - guarded above
        raise ValidationError(f"invalid amount: {text!r}") from exc
    return from_decimal(value, digits=digits)


def format_amount(
    amount: int,
    *,
    currency: str | None = None,
    digits: int = 2,
    decimal_separator: str = ".",
    group_separator: str | None = ",",
    plus_sign: bool = False,
) -> str:
    """Format minor units as a human-readable amount.

    Args:
        amount: Amount in minor units.
        currency: Optional symbol placed before the number. Alphabetic codes such
            as `"EUR"` are followed by a space, symbols such as `"€"` are not.
        digits: Number of minor-unit digits of the currency.
        decimal_separator: Character placed before the decimal digits.
        group_separator: Thousands separator, or `None` for no grouping.
        plus_sign: Whether to prefix positive amounts with `+`.

    Returns:
        The formatted text, for example `"-€1,234.50"`.

    Raises:
        ValidationError: If `amount` is not an integer or `digits` is invalid.
    """
    value = to_decimal(amount, digits=digits)
    sign = "-" if amount < 0 else ("+" if plus_sign and amount > 0 else "")
    integer_part, _, fraction = f"{abs(value):.{digits}f}".partition(".")
    if group_separator:
        groups: list[str] = []
        while len(integer_part) > 3:
            groups.insert(0, integer_part[-3:])
            integer_part = integer_part[:-3]
        groups.insert(0, integer_part)
        integer_part = group_separator.join(groups)
    number = integer_part + (decimal_separator + fraction if digits else "")
    prefix = ""
    if currency:
        prefix = currency + (" " if currency[-1].isalpha() else "")
    return f"{sign}{prefix}{number}"
