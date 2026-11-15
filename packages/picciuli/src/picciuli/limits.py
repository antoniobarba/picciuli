"""Upper bounds on the values a book accepts.

Every service validates its arguments against these limits and raises
[`ValidationError`][picciuli.errors.ValidationError] when one is exceeded. They
keep stored data within the range of SQLite integers, so that totals can always
be computed, and stop a single entry from growing a book without limit.

Example:
    >>> from picciuli.limits import MAX_AMOUNT
    >>> MAX_AMOUNT
    1000000000000000
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

__all__ = [
    "DECIMAL_PLACES",
    "MAX_AMOUNT",
    "MAX_CATEGORY_SYMBOL_LENGTH",
    "MAX_DECIMAL",
    "MAX_ID",
    "MAX_MEMO_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_SPLITS",
    "MAX_SYMBOL_LENGTH",
    "MAX_TEXT_LENGTH",
]

MAX_AMOUNT: Final = 10**15
"""Largest absolute amount, in minor units, of any single value.

It applies to split amounts, opening balances, goals, budgets, costs,
proceeds, fees and taxes: 10 trillion with 2 minor digits, 1 billion with 6.
Balances and totals are sums of such values and may be larger.
"""

MAX_ID: Final = 2**63 - 1
"""Largest identifier of a stored entity (the largest SQLite integer)."""

DECIMAL_PLACES: Final = 8
"""Most decimal places of a share quantity, price or exchange rate."""

MAX_DECIMAL: Final = Decimal(MAX_ID).scaleb(-DECIMAL_PLACES)
"""Largest absolute share quantity, price or exchange rate (about 9.2e10)."""

MAX_SPLITS: Final = 100
"""Most splits a single transaction can have."""

MAX_NAME_LENGTH: Final = 200
"""Longest name of an account, category, security or period, in characters.

It also bounds the currency symbol, provider identifiers and price sources.
"""

MAX_TEXT_LENGTH: Final = 2000
"""Longest description or notes, in characters."""

MAX_MEMO_LENGTH: Final = 500
"""Longest split memo, in characters."""

MAX_SYMBOL_LENGTH: Final = 32
"""Longest ticker symbol of a security, in characters."""

MAX_CATEGORY_SYMBOL_LENGTH: Final = 12
"""Longest short label of a category, in characters."""
