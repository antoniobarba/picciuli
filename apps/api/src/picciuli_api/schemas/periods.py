"""Bodies of the period and budget endpoints."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from .accounts import AccountOut
from .base import InputModel, OutputModel, PatchModel
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

    start: dt.date
    end: dt.date | None = None
    name: str | None = None


class PeriodUpdate(PatchModel):
    """Changes to a period."""

    name: str | None = None
    start: dt.date | None = None
    end: dt.date | None = None


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

    category_id: int
    period_id: int
    amount: int = Field(ge=0)


class BudgetUpdate(PatchModel):
    """Changes to a budget."""

    amount: int | None = Field(default=None, ge=0)
    category_id: int | None = None
    period_id: int | None = None


class BudgetCopy(InputModel):
    """Copy every budget of a period into another one."""

    source_period_id: int
    target_period_id: int
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
