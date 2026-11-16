"""Savings goals: several targets per account, with dates and priorities."""

from __future__ import annotations

import builtins
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._db.queries import account_balances, get_row, to_account, to_goal
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import AccountRow, SavingsGoalRow
from picciuli.errors import ConflictError, ValidationError
from picciuli.model import (
    UNSET,
    AccountType,
    GoalAccount,
    GoalPriority,
    GoalProgress,
    GoalReport,
    GoalStatus,
    SavingsGoal,
    Unset,
)

__all__ = ["GoalService"]


def _priority(value: object) -> GoalPriority:
    try:
        return GoalPriority(value)
    except ValueError:
        allowed = ", ".join(p.value for p in GoalPriority)
        raise ValidationError(
            f"invalid priority {value!r}; expected one of: {allowed}"
        ) from None


def _goal_account(session: Session, account_id: int) -> AccountRow:
    """An open account that can receive goals."""
    row = get_row(session, AccountRow, account_id, "account")
    if not AccountType(row.type).holds_goals:
        raise ValidationError(
            f"account {row.name!r} cannot hold savings goals: only checking, "
            "savings, cash and other asset accounts can"
        )
    if row.closed_on is not None:
        raise ConflictError(f"account {row.name!r} is closed")
    return row


def _ensure_unique_name(
    session: Session, account_id: int, name: str, exclude: int | None = None
) -> None:
    folded = name.casefold()
    existing = session.execute(
        select(SavingsGoalRow.id, SavingsGoalRow.name).where(
            SavingsGoalRow.account_id == account_id
        )
    )
    for row_id, other in existing:
        if row_id != exclude and other.casefold() == folded:
            raise ConflictError(f"the account already has a goal named {other!r}")


def progress(goal: SavingsGoal, today: dt.date) -> GoalProgress:
    """What `goal` still needs on `today`, and how much to save every month."""
    remaining = max(goal.target_amount - goal.saved_amount, 0)
    if remaining == 0:
        return GoalProgress(goal, 0, GoalStatus.REACHED, None, 0)
    target = goal.target_date
    if target is None:
        return GoalProgress(goal, remaining, GoalStatus.UNDATED, None, None)
    if target < today:
        return GoalProgress(goal, remaining, GoalStatus.OVERDUE, None, None)
    months = 12 * (target.year - today.year) + target.month - today.month + 1
    monthly = -(-remaining // months)
    return GoalProgress(goal, remaining, GoalStatus.SCHEDULED, months, monthly)


class GoalService:
    """Manage savings goals and plan how much to save for them.

    Obtain it as [`Book.goals`][picciuli.Book.goals].

    A goal sets aside part of the money of a checking, savings, cash or other
    asset account. An account can hold several goals; you assign their saved
    amounts by hand. Goals never move money: transactions do not change them,
    and they do not change balances, budgets or net worth.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(
        self,
        account_id: int,
        name: str,
        target_amount: int,
        *,
        saved_amount: int = 0,
        target_date: dt.date | None = None,
        priority: GoalPriority | str = GoalPriority.NORMAL,
    ) -> SavingsGoal:
        """Create a savings goal.

        Args:
            account_id: Open checking, savings, cash or other asset account.
            name: Name, unique within the account (case-insensitive).
            target_amount: Amount to reach, in minor units (positive).
            saved_amount: Amount already set aside (zero or more). It may
                exceed the target or the account balance.
            target_date: Day the target should be reached, or `None`.
            priority: Importance, as an enum member or its string value.

        Raises:
            NotFoundError: If the account does not exist.
            ValidationError: If an argument is invalid or the account type
                cannot hold goals.
            ConflictError: If the account is closed or already has a goal with
                that name.
        """
        name = v.name(name, "goal name")
        target_amount = v.positive_amount(target_amount, "target amount")
        saved_amount = v.non_negative_amount(saved_amount, "saved amount")
        target_date = v.optional_date(target_date, "target date")
        rank = _priority(priority)
        with self._uow.session() as session:
            account = _goal_account(session, account_id)
            _ensure_unique_name(session, account.id, name)
            row = SavingsGoalRow(
                account_id=account.id,
                name=name,
                target_amount=target_amount,
                saved_amount=saved_amount,
                target_date=target_date,
                priority=rank.value,
            )
            session.add(row)
            session.flush()
            return to_goal(row)

    def get(self, goal_id: int) -> SavingsGoal:
        """Return a savings goal.

        Raises:
            NotFoundError: If the goal does not exist.
        """
        with self._uow.session() as session:
            return to_goal(get_row(session, SavingsGoalRow, goal_id, "goal"))

    def list(self, *, account_id: int | None = None) -> builtins.list[SavingsGoal]:
        """Return goals by account display order, then priority.

        Args:
            account_id: Only the goals of this account.

        Raises:
            ValidationError: If `account_id` is not a valid id.
        """
        with self._uow.session() as session:
            return self._ordered(session, account_id)

    def update(
        self,
        goal_id: int,
        *,
        account_id: int | Unset = UNSET,
        name: str | Unset = UNSET,
        target_amount: int | Unset = UNSET,
        saved_amount: int | Unset = UNSET,
        target_date: dt.date | None | Unset = UNSET,
        priority: GoalPriority | str | Unset = UNSET,
    ) -> SavingsGoal:
        """Change a goal; arguments left `UNSET` are not modified.

        A goal of a closed account can still be edited; moving it to another
        account requires an open account that can hold goals.

        Raises:
            NotFoundError: If the goal or the new account does not exist.
            ValidationError: If an argument is invalid or the new account type
                cannot hold goals.
            ConflictError: If the new account is closed, or the account
                already has another goal with the name.
        """
        with self._uow.session() as session:
            row = get_row(session, SavingsGoalRow, goal_id, "goal")
            if not isinstance(account_id, Unset) and account_id != row.account_id:
                row.account_id = _goal_account(session, account_id).id
            if not isinstance(name, Unset):
                row.name = v.name(name, "goal name")
            if not isinstance(target_amount, Unset):
                row.target_amount = v.positive_amount(target_amount, "target amount")
            if not isinstance(saved_amount, Unset):
                row.saved_amount = v.non_negative_amount(saved_amount, "saved amount")
            if not isinstance(target_date, Unset):
                row.target_date = v.optional_date(target_date, "target date")
            if not isinstance(priority, Unset):
                row.priority = _priority(priority).value
            _ensure_unique_name(session, row.account_id, row.name, exclude=row.id)
            session.flush()
            return to_goal(row)

    def delete(self, goal_id: int) -> None:
        """Delete a goal. The money of the account does not change.

        Raises:
            NotFoundError: If the goal does not exist.
        """
        with self._uow.session() as session:
            session.delete(get_row(session, SavingsGoalRow, goal_id, "goal"))

    def report(self, *, today: dt.date | None = None) -> GoalReport:
        """Every goal with what it still needs, grouped by account.

        Each account compares the total saved amount of its goals with its
        balance at the end of `today`, so that a shortfall shows when the
        goals claim more money than the account holds.

        Args:
            today: The planning day; defaults to the actual date.
        """
        today = v.optional_date(today, "today") or dt.date.today()
        with self._uow.session() as session:
            goals = self._ordered(session, None)
            ids = {goal.account_id for goal in goals}
            balances = account_balances(session, until=today, account_ids=ids)
            accounts = {
                row.id: row
                for row in session.scalars(
                    select(AccountRow).where(AccountRow.id.in_(ids))
                )
            }
            groups: dict[int, builtins.list[SavingsGoal]] = {}
            for goal in goals:
                groups.setdefault(goal.account_id, []).append(goal)
            result = []
            for account_id, items in groups.items():
                balance = balances[account_id]
                assigned = sum(goal.saved_amount for goal in items)
                available = max(balance, 0)
                result.append(
                    GoalAccount(
                        account=to_account(accounts[account_id]),
                        balance=balance,
                        assigned=assigned,
                        unassigned=max(available - assigned, 0),
                        shortfall=max(assigned - available, 0),
                        goals=tuple(progress(goal, today) for goal in items),
                    )
                )
            return GoalReport(today=today, accounts=tuple(result))

    @staticmethod
    def _ordered(
        session: Session, account_id: int | None
    ) -> builtins.list[SavingsGoal]:
        statement = select(SavingsGoalRow, AccountRow.position).join(
            AccountRow, AccountRow.id == SavingsGoalRow.account_id
        )
        if account_id is not None:
            account_id = v.identifier(account_id, "account id")
            statement = statement.where(SavingsGoalRow.account_id == account_id)
        rows = [
            (position, row.account_id, to_goal(row))
            for row, position in session.execute(statement)
        ]
        rows.sort(
            key=lambda item: (item[0], item[1], item[2].priority.rank, item[2].id)
        )
        return [goal for _, _, goal in rows]
