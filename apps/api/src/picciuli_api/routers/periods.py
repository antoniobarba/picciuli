"""Period and budget endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from picciuli_api.deps import BookDep
from picciuli_api.schemas.base import Date, PathId, QueryId
from picciuli_api.schemas.periods import (
    BudgetCopy,
    BudgetCreate,
    BudgetOut,
    BudgetReportOut,
    BudgetUpdate,
    PeriodChangeOut,
    PeriodCreate,
    PeriodOut,
    PeriodRegenerate,
    PeriodSummaryOut,
    PeriodUpdate,
)

periods = APIRouter(prefix="/periods", tags=["periods"])
budgets = APIRouter(prefix="/budgets", tags=["budgets"])


@periods.get("")
def list_periods(
    book: BookDep,
    on: Annotated[
        Date | None, Query(description="Only the periods containing this day.")
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


@periods.get("/regenerate")
def preview_regeneration(book: BookDep, today: Date) -> list[PeriodChangeOut]:
    """Preview how existing periods would follow the monthly period settings."""
    changes = book.periods.regenerate(today, dry_run=True)
    return [PeriodChangeOut.model_validate(c) for c in changes]


@periods.post("/regenerate")
def regenerate_periods(book: BookDep, body: PeriodRegenerate) -> list[PeriodChangeOut]:
    """Align existing periods with the monthly period settings.

    Periods get new dates and names but keep their budgets; missing monthly
    periods are created; nothing is deleted.
    """
    changes = book.periods.regenerate(body.today)
    return [PeriodChangeOut.model_validate(c) for c in changes]


@periods.get("/{period_id:int}")
def get_period(book: BookDep, period_id: PathId) -> PeriodOut:
    """Get one period."""
    return PeriodOut.model_validate(book.periods.get(period_id))


@periods.patch("/{period_id:int}")
def update_period(book: BookDep, period_id: PathId, body: PeriodUpdate) -> PeriodOut:
    """Change the name or the days of a period."""
    return PeriodOut.model_validate(book.periods.update(period_id, **body.changes()))


@periods.delete("/{period_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_period(book: BookDep, period_id: PathId) -> None:
    """Delete a period and its budgets."""
    book.periods.delete(period_id)


@periods.get("/{period_id:int}/summary")
def period_summary(book: BookDep, period_id: PathId) -> PeriodSummaryOut:
    """Flows by category and balance changes by account during a period."""
    return PeriodSummaryOut.model_validate(book.periods.summary(period_id))


@periods.get("/{period_id:int}/budget-report")
def budget_report(book: BookDep, period_id: PathId) -> BudgetReportOut:
    """Budgets of a period compared with the actual flows."""
    return BudgetReportOut.model_validate(book.budgets.report(period_id))


@budgets.get("")
def list_budgets(
    book: BookDep, period_id: QueryId = None, category_id: QueryId = None
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


@budgets.get("/{budget_id:int}")
def get_budget(book: BookDep, budget_id: PathId) -> BudgetOut:
    """Get one budget."""
    return BudgetOut.model_validate(book.budgets.get(budget_id))


@budgets.patch("/{budget_id:int}")
def update_budget(book: BookDep, budget_id: PathId, body: BudgetUpdate) -> BudgetOut:
    """Change a budget."""
    return BudgetOut.model_validate(book.budgets.update(budget_id, **body.changes()))


@budgets.delete("/{budget_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(book: BookDep, budget_id: PathId) -> None:
    """Delete a budget."""
    book.budgets.delete(budget_id)
