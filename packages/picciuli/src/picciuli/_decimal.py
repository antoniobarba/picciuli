"""Exact decimal helpers for quantities, prices and exchange rates (private).

Those values are `Decimal` in the API and integers scaled by `SCALE` in the
database, so that no float ever touches stored data.
"""

from __future__ import annotations

import decimal
from decimal import Decimal
from typing import Final

from picciuli.errors import ValidationError
from picciuli.limits import DECIMAL_PLACES, MAX_DECIMAL

PLACES: Final = DECIMAL_PLACES
"""Maximum number of decimal places of quantities, prices and rates."""

SCALE: Final = 10**PLACES

_QUANTUM: Final = Decimal(1).scaleb(-PLACES)
_LIMIT: Final = MAX_DECIMAL


def to_decimal(value: object, field: str) -> Decimal:
    """Validate a finite `Decimal` or `int` with at most `PLACES` decimals."""
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValidationError(f"{field} must be a Decimal or an integer")
    result = Decimal(value)
    if not result.is_finite():
        raise ValidationError(f"{field} must be a finite number")
    # Checked first: quantizing a huge value raises InvalidOperation.
    if result.copy_abs() > _LIMIT:
        raise ValidationError(f"{field} is too large")
    if result != result.quantize(_QUANTUM, rounding=decimal.ROUND_DOWN):
        raise ValidationError(f"{field} can have at most {PLACES} decimal places")
    return result


def positive_decimal(value: object, field: str) -> Decimal:
    result = to_decimal(value, field)
    if result <= 0:
        raise ValidationError(f"{field} must be greater than zero")
    return result


def rounded(value: Decimal) -> Decimal:
    """Round a provider value to `PLACES` decimals (half-even)."""
    return value.quantize(_QUANTUM, rounding=decimal.ROUND_HALF_EVEN)


def to_scaled(value: Decimal) -> int:
    return int((value * SCALE).to_integral_value())


def from_scaled(value: int) -> Decimal:
    return (Decimal(value) / SCALE).normalize()


def market_value(
    quantity: Decimal, price: Decimal, rate: Decimal, minor_digits: int
) -> int:
    """`quantity * price * rate` in minor units, rounded half-even."""
    with decimal.localcontext() as context:
        context.prec = 80
        value = quantity * price * rate * (10**minor_digits)
        return int(value.to_integral_value(rounding=decimal.ROUND_HALF_EVEN))


def share_of(amount: int, part: Decimal, whole: Decimal) -> int:
    """`amount * part / whole` in minor units, rounded half-even."""
    with decimal.localcontext() as context:
        context.prec = 80
        value = Decimal(amount) * part / whole
        return int(value.to_integral_value(rounding=decimal.ROUND_HALF_EVEN))
