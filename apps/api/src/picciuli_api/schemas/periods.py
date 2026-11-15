"""Bodies of the period and budget endpoints."""

from __future__ import annotations

import datetime as dt

from .accounts import AccountOut
from .base import (
    Date,
    Id,
    InputModel,
    Name,
    NonNegativeAmount,
    OutputModel,
    PatchModel,
)
from .categories import CategoryOut

__all__ = [
    "AccountChangeOut",
    "BudgetCopy",
    "BudgetCreate",
    "BudgetLineOut",
    "BudgetOut",
    "BudgetReportOut",
    "BudgetUpdate",
    "CategoryTotalOut",
    "PeriodCreate",
    "PeriodOut",
    "PeriodSummaryOut",
    "PeriodUpdate",
]


class PeriodOut(OutputModel):
    """A named range of days. `end: null` means the period is still open."""

    id: int
    name: str
    start: dt.date
    end: dt.date | None


class PeriodCreate(InputModel):
    """A new period. Its name defaults to one derived from the dates."""

    start: Date
    end: Date | None = None
    name: Name | None = None


class PeriodUpdate(PatchModel):
    """Changes to a period."""

    _not_null = frozenset({"name", "start"})

    name: Name | None = None
    start: Date | None = None
    end: Date | None = None


class CategoryTotalOut(OutputModel):
    """External flows of one category."""

    category: CategoryOut
    amount: int
    total: int


class AccountChangeOut(OutputModel):
    """How an account balance changed over a period."""

    account: AccountOut
    opening: int
    closing: int
    change: int


class PeriodSummaryOut(OutputModel):
    """Totals of a period by category and by account."""

    period: PeriodOut
    categories: list[CategoryTotalOut]
    uncategorized: int
    income: int
    expenses: int
    net: int
    accounts: list[AccountChangeOut]


class BudgetOut(OutputModel):
    """A spending allowance for a category in a period."""

    id: int
    category_id: int
    period_id: int
    amount: int


class BudgetCreate(InputModel):
    """A new budget."""

    category_id: Id
    period_id: Id
    amount: NonNegativeAmount


class BudgetUpdate(PatchModel):
    """Changes to a budget."""

    _not_null = frozenset({"amount", "category_id", "period_id"})

    amount: NonNegativeAmount | None = None
    category_id: Id | None = None
    period_id: Id | None = None


class BudgetCopy(InputModel):
    """Copy every budget of a period into another one."""

    source_period_id: Id
    target_period_id: Id
    overwrite: bool = False


class BudgetLineOut(OutputModel):
    """Status of one budget."""

    budget: BudgetOut
    category: CategoryOut
    actual: int
    remaining: int


class BudgetReportOut(OutputModel):
    """Status of all budgets of a period."""

    period: PeriodOut
    lines: list[BudgetLineOut]
    total_budget: int
    total_actual: int
    total_remaining: int
