"""Savings goal endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from picciuli_api.deps import BookDep
from picciuli_api.schemas.base import PathId, QueryDate, QueryId
from picciuli_api.schemas.goals import (
    GoalCreate,
    GoalOut,
    GoalReportOut,
    GoalUpdate,
)

router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("")
def list_goals(book: BookDep, account_id: QueryId = None) -> list[GoalOut]:
    """List the savings goals by account, then priority."""
    return [GoalOut.model_validate(g) for g in book.goals.list(account_id=account_id)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_goal(book: BookDep, body: GoalCreate) -> GoalOut:
    """Create a savings goal. The saved amount may exceed the account balance."""
    goal = book.goals.create(
        body.account_id,
        body.name,
        body.target_amount,
        saved_amount=body.saved_amount,
        target_date=body.target_date,
        priority=body.priority,
    )
    return GoalOut.model_validate(goal)


@router.get("/report")
def goal_report(book: BookDep, today: QueryDate = None) -> GoalReportOut:
    """Every goal with the monthly amount it needs, grouped by account.

    `today` is the planning day (default: the server date). Each account
    shows a `shortfall` when its goals claim more than its balance.
    """
    return GoalReportOut.model_validate(book.goals.report(today=today))


@router.get("/{goal_id:int}")
def get_goal(book: BookDep, goal_id: PathId) -> GoalOut:
    """Get one savings goal."""
    return GoalOut.model_validate(book.goals.get(goal_id))


@router.patch("/{goal_id:int}")
def update_goal(book: BookDep, goal_id: PathId, body: GoalUpdate) -> GoalOut:
    """Change some fields of a savings goal."""
    return GoalOut.model_validate(book.goals.update(goal_id, **body.changes()))


@router.delete("/{goal_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(book: BookDep, goal_id: PathId) -> None:
    """Delete a savings goal; no money moves."""
    book.goals.delete(goal_id)
