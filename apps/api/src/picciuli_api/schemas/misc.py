"""Bodies of the register, settings and user endpoints."""

from __future__ import annotations

from picciuli import CostMethod

from .accounts import AccountOut
from .base import OutputModel, PatchModel
from .transactions import TransactionOut

__all__ = [
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


class SettingsUpdate(PatchModel):
    """Changes to the settings."""

    currency: str | None = None
    minor_digits: int | None = None
    currency_code: str | None = None
    cost_method: CostMethod | None = None
    price_provider: str | None = None
    rate_provider: str | None = None


class MeOut(OutputModel):
    """The authenticated user."""

    id: str
    """Opaque identifier of the user's data."""
    issuer: str
    subject: str
