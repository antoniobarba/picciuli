"""Bodies of the register, settings and user endpoints."""

from __future__ import annotations

from pydantic import Field

from picciuli import CostMethod

from .accounts import AccountOut
from .base import CurrencyCode, Name, OutputModel, PatchModel
from .transactions import TransactionOut

__all__ = [
    "ImportOut",
    "MeOut",
    "RegisterEntryOut",
    "RegisterOut",
    "SettingsOut",
    "SettingsUpdate",
]


class RegisterEntryOut(OutputModel):
    """A transaction seen from one account, with the running balance."""

    transaction: TransactionOut
    amount: int
    balance: int


class RegisterOut(OutputModel):
    """The ledger of one account."""

    account: AccountOut
    starting_balance: int
    entries: list[RegisterEntryOut]
    ending_balance: int


class SettingsOut(OutputModel):
    """Book-wide settings."""

    currency: str
    minor_digits: int
    currency_code: str | None
    cost_method: CostMethod
    price_provider: str
    rate_provider: str
    period_start_day: int | None = Field(
        description="Day of the month monthly periods start on (for example "
        "your payday), or `null` when periods are created by hand."
    )
    period_weekend_shift: bool = Field(
        description="Whether monthly periods starting on a weekend start on "
        "the Friday before."
    )


class SettingsUpdate(PatchModel):
    """Changes to the settings."""

    _not_null = frozenset(
        {
            "currency",
            "minor_digits",
            "cost_method",
            "price_provider",
            "rate_provider",
            "period_weekend_shift",
        }
    )

    currency: Name | None = None
    minor_digits: int | None = Field(default=None, ge=0, le=6)
    currency_code: CurrencyCode | None = None
    cost_method: CostMethod | None = None
    price_provider: Name | None = None
    rate_provider: Name | None = None
    period_start_day: int | None = Field(default=None, ge=1, le=31)
    period_weekend_shift: bool | None = None


class MeOut(OutputModel):
    """The authenticated user."""

    id: str
    """Opaque identifier of the user's data."""
    issuer: str
    subject: str


class ImportOut(OutputModel):
    """What an import added to your book (reused entities are not counted)."""

    replaced: bool
    """Whether the previous data was erased first."""
    accounts: int
    categories: int
    securities: int
    prices: int
    exchange_rates: int
    periods: int
    budgets: int
    transactions: int
    duplicates: int
    """Transactions skipped because an identical one already existed."""
    schedules: int
