"""Period and budget endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query, status

from picciuli_api.deps import BookDep
from picciuli_api.schemas.periods import (
    BudgetCopy,
    BudgetCreate,
    BudgetOut,
    BudgetReportOut,
    BudgetUpdate,
    PeriodCreate,
    PeriodOut,
    PeriodSummaryOut,
    PeriodUpdate,
)

periods = APIRouter(prefix="/periods", tags=["periods"])
budgets = APIRouter(prefix="/budgets", tags=["budgets"])


@periods.get("")
def list_periods(
    book: BookDep,
    on: Annotated[
        dt.date | None, Query(description="Only the periods containing this day.")
    ] = None,
) -> list[PeriodOut]:
    """List the periods."""
    found = book.periods.list() if on is None else book.periods.periods_on(on)
    return [PeriodOut.model_validate(p) for p in found]


@periods.post("", status_code=status.HTTP_201_CREATED)
def create_period(book: BookDep, body: PeriodCreate) -> PeriodOut:
    """Create a period.

    A new open-ended period closes the earlier open-ended ones on the day
    before it starts.
    """
    period = book.periods.create(body.start, end=body.end, name=body.name)
    return PeriodOut.model_validate(period)


@periods.get("/{period_id}")
def get_period(book: BookDep, period_id: int) -> PeriodOut:
    """Get one period."""
    return PeriodOut.model_validate(book.periods.get(period_id))


@periods.patch("/{period_id}")
def update_period(book: BookDep, period_id: int, body: PeriodUpdate) -> PeriodOut:
    """Change the name or the days of a period."""
    return PeriodOut.model_validate(book.periods.update(period_id, **body.changes()))


@periods.delete("/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_period(book: BookDep, period_id: int) -> None:
    """Delete a period and its budgets."""
    book.periods.delete(period_id)


@periods.get("/{period_id}/summary")
def period_summary(book: BookDep, period_id: int) -> PeriodSummaryOut:
    """Flows by category and balance changes by account during a period."""
    return PeriodSummaryOut.model_validate(book.periods.summary(period_id))


@periods.get("/{period_id}/budget-report")
def budget_report(book: BookDep, period_id: int) -> BudgetReportOut:
    """Budgets of a period compared with the actual flows."""
    return BudgetReportOut.model_validate(book.budgets.report(period_id))


@budgets.get("")
def list_budgets(
    book: BookDep, period_id: int | None = None, category_id: int | None = None
) -> list[BudgetOut]:
    """List the budgets, optionally of one period or category."""
    found = book.budgets.list(period_id=period_id, category_id=category_id)
    return [BudgetOut.model_validate(b) for b in found]


@budgets.post("", status_code=status.HTTP_201_CREATED)
def create_budget(book: BookDep, body: BudgetCreate) -> BudgetOut:
    """Create a budget for a category in a period."""
    budget = book.budgets.create(body.category_id, body.period_id, body.amount)
    return BudgetOut.model_validate(budget)


@budgets.post("/copy")
def copy_budgets(book: BookDep, body: BudgetCopy) -> list[BudgetOut]:
    """Copy the budgets of a period into another one and return those created."""
    copied = book.budgets.copy(
        body.source_period_id, body.target_period_id, overwrite=body.overwrite
    )
    return [BudgetOut.model_validate(b) for b in copied]


@budgets.get("/{budget_id}")
def get_budget(book: BookDep, budget_id: int) -> BudgetOut:
    """Get one budget."""
    return BudgetOut.model_validate(book.budgets.get(budget_id))


@budgets.patch("/{budget_id}")
def update_budget(book: BookDep, budget_id: int, body: BudgetUpdate) -> BudgetOut:
    """Change a budget."""
    return BudgetOut.model_validate(book.budgets.update(budget_id, **body.changes()))


@budgets.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(book: BookDep, budget_id: int) -> None:
    """Delete a budget."""
    book.budgets.delete(budget_id)
