"""Bodies of the account endpoints."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from picciuli import AccountClass, AccountType

from .base import (
    Amount,
    Date,
    InputModel,
    Name,
    OutputModel,
    PatchModel,
    Position,
    Text,
)

__all__ = [
    "AccountBalanceOut",
    "AccountCreate",
    "AccountMove",
    "AccountOut",
    "AccountTrendOut",
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

    name: Name = Field(examples=["Checking"])
    type: AccountType
    opening_balance: Amount = 0
    opening_date: Date | None = None
    goal: Amount | None = None
    notes: Text | None = None


class AccountUpdate(PatchModel):
    """Changes to an account."""

    _not_null = frozenset({"name", "type", "opening_balance"})

    name: Name | None = None
    type: AccountType | None = None
    opening_balance: Amount | None = None
    opening_date: Date | None = None
    goal: Amount | None = None
    notes: Text | None = None


class AccountMove(InputModel):
    """A new display position."""

    position: Position


class CloseAccount(InputModel):
    """When to close an account."""

    on: Date | None = None
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


class AccountTrendOut(OutputModel):
    """How the balance of an account has been moving."""

    account: AccountOut
    balance: int
    """Balance including every transaction."""
    months: int
    """Complete months averaged, from the first transaction to last month."""
    average_flow: int | None
    """Average net change per month; `null` without complete months."""
    low_point: int | None
    """Lowest balance of the current debt; `null` when not negative."""


class NetWorthOut(OutputModel):
    """Totals of all account balances."""

    as_of: dt.date | None
    assets: int
    liabilities: int
    net_worth: int
