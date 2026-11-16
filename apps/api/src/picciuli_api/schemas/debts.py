"""Bodies of the debt endpoints and of the debt terms of accounts."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from picciuli import DebtLinkKind, PayoffStrategy, Rollover

from .accounts import AccountOut, DebtChargeOut
from .base import (
    Date,
    DecimalStr,
    Id,
    InputModel,
    NonNegativeAmount,
    OutputModel,
    Percent,
    PositiveAmount,
    Text,
)

__all__ = [
    "DebtPayoffOut",
    "DebtPlanIn",
    "DebtPlanOut",
    "DebtPlansOut",
    "DebtStatusOut",
    "LoanPaymentIn",
    "LoanPaymentSplitOut",
    "LumpSumIn",
    "PlanMonthOut",
    "ScheduleDebtIn",
    "ScheduleDebtOut",
]

MAX_LUMP_SUMS = 100


class ScheduleDebtOut(OutputModel):
    """The debt a recurring transaction pays or charges."""

    kind: DebtLinkKind
    account_id: int
    interest_category_id: int | None


class ScheduleDebtIn(InputModel):
    """Makes a recurring transaction a loan payment.

    Each occurrence is split into principal and interest when posted. The
    splits must move money from one account into the loan.
    """

    kind: Literal[DebtLinkKind.LOAN_PAYMENT] = DebtLinkKind.LOAN_PAYMENT
    account_id: Id = Field(description="The loan.")
    interest_category_id: Id | None = Field(
        default=None,
        description="Category of the interest; defaults to the loan's.",
    )


class DebtStatusOut(OutputModel):
    """A liability with terms, and when it is paid off at the minimum payment."""

    account: AccountOut
    balance: int = Field(description="Balance up to today (negative when owed).")
    owed: int
    minimum_payment: int | None = Field(
        description="What is due every month now, a loan's fixed charges included."
    )
    next_due: dt.date | None
    payoff: dt.date | None = Field(
        description="First day of the month the debt is paid off at the "
        "minimum payment, with interest; `null` if never or unknown."
    )
    interest_to_payoff: int | None
    charges_to_payoff: int | None = Field(
        description="Fixed charges of a loan paid until then; `null` with `payoff`."
    )


class LumpSumIn(InputModel):
    """A one-off extra payment."""

    date: Date = Field(description="Any day of the month it is paid in.")
    amount: PositiveAmount


class DebtPlanIn(InputModel):
    """How to simulate paying off the debts."""

    extra: NonNegativeAmount = Field(
        default=0, description="Extra payment every month."
    )
    lump_sums: list[LumpSumIn] = Field(default=[], max_length=MAX_LUMP_SUMS)
    rollover: Rollover = Rollover.FULL
    rollover_percent: Percent | None = Field(
        default=None,
        description="With a partial rollover, the percentage of a paid-off "
        "debt's payment that goes to the next one (default 50).",
    )
    today: Date | None = Field(
        default=None, description="The plan starts the month after this day."
    )


class DebtPayoffOut(OutputModel):
    """How one debt is paid off."""

    account_id: int
    order: int
    balance: int
    payoff: dt.date | None
    interest: int
    paid: int = Field(description="Total paid, fixed charges included.")
    charges: int = Field(description="Fixed charges of a loan paid.")


class PlanMonthOut(OutputModel):
    """One month of a plan."""

    month: dt.date
    payment: int = Field(description="Total paid, fixed charges included.")
    interest: int
    balance: int
    balances: list[int] = Field(description="Owed on each debt, in plan order.")


class DebtPlanOut(OutputModel):
    """A month-by-month payoff simulation."""

    strategy: PayoffStrategy
    rollover: Rollover
    rollover_percent: DecimalStr | None
    extra: int
    monthly_budget: int
    debts: list[DebtPayoffOut]
    months: list[PlanMonthOut]
    payoff: dt.date | None = Field(
        description="When the last debt is paid off; `null` beyond 100 years."
    )
    total_interest: int
    total_paid: int
    total_charges: int


class DebtPlansOut(OutputModel):
    """The snowball and avalanche strategies, side by side."""

    snowball: DebtPlanOut
    avalanche: DebtPlanOut


class LoanPaymentSplitOut(OutputModel):
    """How a payment into a loan divides into interest, charges and principal."""

    account_id: int
    date: dt.date
    amount: int
    owed: int
    interest: int
    principal: int
    charges: list[DebtChargeOut] = Field(
        description="The loan's fixed charges, with the amounts actually "
        "charged after the interest."
    )


class LoanPaymentIn(InputModel):
    """A payment into a loan, split into principal, interest and fixed charges."""

    date: Date
    amount: PositiveAmount
    from_account_id: Id
    interest_category_id: Id | None = Field(
        default=None, description="Defaults to the loan's interest category."
    )
    description: Text | None = None
    notes: Text | None = None
