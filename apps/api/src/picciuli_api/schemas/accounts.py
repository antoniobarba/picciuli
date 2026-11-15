"""Bodies of the account endpoints."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from picciuli import AccountClass, AccountType

from .base import InputModel, OutputModel, PatchModel

__all__ = [
    "AccountBalanceOut",
    "AccountCreate",
    "AccountMove",
    "AccountOut",
    "AccountUpdate",
    "BalanceOut",
    "CloseAccount",
    "NetWorthOut",
]


class AccountOut(OutputModel):
    """A place where money is kept or owed."""

    id: int
    name: str
    type: AccountType
    account_class: AccountClass
    opening_balance: int
    opening_date: dt.date | None
    goal: int | None
    notes: str | None
    position: int
    closed_on: dt.date | None
    is_closed: bool


class AccountCreate(InputModel):
    """A new account."""

    name: str = Field(examples=["Checking"])
    type: AccountType
    opening_balance: int = 0
    opening_date: dt.date | None = None
    goal: int | None = None
    notes: str | None = None


class AccountUpdate(PatchModel):
    """Changes to an account."""

    name: str | None = None
    type: AccountType | None = None
    opening_balance: int | None = None
    opening_date: dt.date | None = None
    goal: int | None = None
    notes: str | None = None


class AccountMove(InputModel):
    """A new display position."""

    position: int = Field(ge=1)


class CloseAccount(InputModel):
    """When to close an account."""

    on: dt.date | None = None
    """Closing day; today if omitted."""


class BalanceOut(OutputModel):
    """The balance of one account."""

    account_id: int
    as_of: dt.date | None
    balance: int


class AccountBalanceOut(OutputModel):
    """An account with its balance."""

    account: AccountOut
    balance: int


class NetWorthOut(OutputModel):
    """Totals of all account balances."""

    as_of: dt.date | None
    assets: int
    liabilities: int
    net_worth: int
