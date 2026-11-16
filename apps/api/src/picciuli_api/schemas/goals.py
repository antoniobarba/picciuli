"""Bodies of the savings goal endpoints."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from picciuli import GoalPriority, GoalStatus

from .accounts import AccountOut
from .base import (
    Date,
    Id,
    InputModel,
    Name,
    NonNegativeAmount,
    OutputModel,
    PatchModel,
    PositiveAmount,
)

__all__ = [
    "GoalAccountOut",
    "GoalCreate",
    "GoalOut",
    "GoalProgressOut",
    "GoalReportOut",
    "GoalUpdate",
]


class GoalOut(OutputModel):
    """Money set aside by hand in one account, for example for a holiday."""

    id: int
    account_id: int
    name: str
    target_amount: int
    saved_amount: int
    """Assigned by hand; transactions never change it."""
    target_date: dt.date | None
    priority: GoalPriority


class GoalCreate(InputModel):
    """A new savings goal, in an open checking, savings, cash or other asset account."""

    account_id: Id
    name: Name = Field(examples=["Holiday"])
    target_amount: PositiveAmount
    saved_amount: NonNegativeAmount = 0
    target_date: Date | None = None
    priority: GoalPriority = GoalPriority.NORMAL


class GoalUpdate(PatchModel):
    """Changes to a savings goal; `target_date: null` removes the date."""

    _not_null = frozenset(
        {"account_id", "name", "target_amount", "saved_amount", "priority"}
    )

    account_id: Id | None = None
    name: Name | None = None
    target_amount: PositiveAmount | None = None
    saved_amount: NonNegativeAmount | None = None
    target_date: Date | None = None
    priority: GoalPriority | None = None


class GoalProgressOut(OutputModel):
    """A goal and what it still needs on the planning day."""

    goal: GoalOut
    remaining: int
    status: GoalStatus
    months_left: int | None = Field(
        description="Months to save in, counting the current month and the "
        "target month; `null` unless `scheduled`."
    )
    monthly_amount: int | None = Field(
        description="What to set aside every month to reach the target on time; "
        "0 once reached, `null` for undated or overdue goals."
    )


class GoalAccountOut(OutputModel):
    """The goals of one account compared with its balance."""

    account: AccountOut
    balance: int
    assigned: int
    """Total saved amount of the goals."""
    unassigned: int
    """Money of the balance not assigned to any goal."""
    shortfall: int
    """How much the goals claim beyond the balance; 0 when they are covered."""
    goals: list[GoalProgressOut]


class GoalReportOut(OutputModel):
    """Every goal on a planning day, grouped by account in display order."""

    today: dt.date
    accounts: list[GoalAccountOut]
