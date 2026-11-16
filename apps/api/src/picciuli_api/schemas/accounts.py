"""Bodies of the account endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from pydantic import Field, model_validator

from picciuli import AccountClass, AccountType, DebtTerms

from .base import (
    Amount,
    Date,
    DecimalStr,
    Id,
    InputModel,
    Name,
    OutputModel,
    PatchModel,
    Percent,
    Position,
    PositiveAmount,
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
    "DebtTermsIn",
    "DebtTermsOut",
    "NetWorthOut",
]


Day = Annotated[
    int,
    Field(ge=1, le=31, description="Day of the month; shorter months use their last."),
]


class DebtTermsOut(OutputModel):
    """Interest and payment terms of a liability."""

    annual_rate: DecimalStr = Field(description="Annual interest rate in percent.")
    payment: int | None = Field(
        description="Loans: the monthly payment. Credit cards: the minimum "
        "payment floor."
    )
    payment_percent: DecimalStr | None = Field(
        description="Credit cards: the minimum payment in percent of the "
        "statement balance."
    )
    due_day: int | None
    statement_day: int | None
    credit_limit: int | None
    payment_account_id: int | None
    interest_category_id: int | None
    propose_interest: bool = Field(
        description="Credit cards: an interest charge waits for confirmation "
        "on every statement day."
    )
    propose_minimum: bool = Field(
        description="Credit cards: the minimum payment waits for confirmation "
        "on every due day."
    )


class DebtTermsIn(InputModel):
    """Interest and payment terms of a credit card, loan, mortgage or other debt.

    Payment percent, statement day, credit limit and the proposals only apply
    to credit cards.
    """

    annual_rate: Percent = Field(examples=["19.9"])
    payment: PositiveAmount | None = None
    payment_percent: Percent | None = None
    due_day: Day | None = None
    statement_day: Day | None = None
    credit_limit: PositiveAmount | None = None
    payment_account_id: Id | None = None
    interest_category_id: Id | None = None
    new_interest_category: Name | None = Field(
        default=None,
        description="Name of the interest category to use, created if no "
        "category has it; instead of `interest_category_id`.",
        examples=["Visa interest"],
    )
    propose_interest: bool = False
    propose_minimum: bool = False

    @model_validator(mode="after")
    def _one_category(self) -> DebtTermsIn:
        if self.interest_category_id is not None and self.new_interest_category:
            raise ValueError(
                "give either interest_category_id or new_interest_category"
            )
        return self

    def to_model(self, interest_category_id: int | None) -> DebtTerms:
        """The library terms, with the resolved interest category."""
        return DebtTerms(
            annual_rate=self.annual_rate,
            payment=self.payment,
            payment_percent=self.payment_percent,
            due_day=self.due_day,
            statement_day=self.statement_day,
            credit_limit=self.credit_limit,
            payment_account_id=self.payment_account_id,
            interest_category_id=interest_category_id,
            propose_interest=self.propose_interest,
            propose_minimum=self.propose_minimum,
        )


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
    debt_terms: DebtTermsOut | None = Field(
        default=None, description="Interest and payment terms of a liability."
    )


class AccountCreate(InputModel):
    """A new account."""

    name: Name = Field(examples=["Checking"])
    type: AccountType
    opening_balance: Amount = 0
    opening_date: Date | None = None
    goal: Amount | None = None
    notes: Text | None = None
    debt_terms: DebtTermsIn | None = Field(
        default=None, description="Terms of a credit card, loan or mortgage."
    )


class AccountUpdate(PatchModel):
    """Changes to an account."""

    _not_null = frozenset({"name", "type", "opening_balance"})

    name: Name | None = None
    type: AccountType | None = None
    opening_balance: Amount | None = None
    opening_date: Date | None = None
    goal: Amount | None = None
    notes: Text | None = None
    debt_terms: DebtTermsIn | None = Field(
        default=None, description="New debt terms; `null` removes them."
    )


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
    """Complete months averaged: the last 3, or fewer for a newer account."""
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
