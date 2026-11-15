"""Budgets: spending allowances per category and period."""

from __future__ import annotations

import builtins

from sqlalchemy import select

from picciuli import _validation as v
from picciuli._db.queries import (
    external_flows,
    get_row,
    ordered_categories,
    rollup,
    to_budget,
    to_category,
    to_period,
)
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import BudgetRow, CategoryRow, PeriodRow
from picciuli.errors import ConflictError, ValidationError
from picciuli.model import UNSET, Budget, BudgetLine, BudgetReport, Unset

__all__ = ["BudgetService"]


def _amount(value: object) -> int:
    return v.non_negative_amount(value, "budget amount")


class BudgetService:
    """Manage budgets and compare them with actual flows.

    Obtain it as [`Book.budgets`][picciuli.Book.budgets].

    A budget is an allowance for one category during one period; each
    (category, period) pair has at most one budget. A budget on a top-level
    category covers its subcategories too. Only external flows count: transfers
    between your own accounts never consume a budget.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(self, category_id: int, period_id: int, amount: int) -> Budget:
        """Create a budget.

        Args:
            category_id: Budgeted category.
            period_id: Period the budget applies to.
            amount: Allowance in minor units (zero or positive).

        Raises:
            ValidationError: If the amount is invalid.
            NotFoundError: If the category or period does not exist.
            ConflictError: If the category already has a budget in the period.
        """
        amount = _amount(amount)
        with self._uow.session() as session:
            get_row(session, CategoryRow, category_id, "category")
            get_row(session, PeriodRow, period_id, "period")
            if session.scalar(
                select(BudgetRow.id).where(
                    BudgetRow.category_id == category_id,
                    BudgetRow.period_id == period_id,
                )
            ):
                raise ConflictError("the category already has a budget in this period")
            row = BudgetRow(category_id=category_id, period_id=period_id, amount=amount)
            session.add(row)
            session.flush()
            return to_budget(row)

    def get(self, budget_id: int) -> Budget:
        """Return a budget.

        Raises:
            NotFoundError: If the budget does not exist.
        """
        with self._uow.session() as session:
            return to_budget(get_row(session, BudgetRow, budget_id, "budget"))

    def list(
        self, *, period_id: int | None = None, category_id: int | None = None
    ) -> builtins.list[Budget]:
        """Return budgets, optionally filtered by period and/or category.

        Raises:
            ValidationError: If an identifier is not a valid id.
        """
        statement = select(BudgetRow)
        if period_id is not None:
            period_id = v.identifier(period_id, "period id")
            statement = statement.where(BudgetRow.period_id == period_id)
        if category_id is not None:
            category_id = v.identifier(category_id, "category id")
            statement = statement.where(BudgetRow.category_id == category_id)
        statement = statement.order_by(
            BudgetRow.period_id, BudgetRow.category_id, BudgetRow.id
        )
        with self._uow.session() as session:
            return [to_budget(row) for row in session.scalars(statement)]

    def update(
        self,
        budget_id: int,
        *,
        amount: int | Unset = UNSET,
        category_id: int | Unset = UNSET,
        period_id: int | Unset = UNSET,
    ) -> Budget:
        """Change a budget; arguments left `UNSET` are not modified.

        Raises:
            NotFoundError: If the budget, category or period does not exist.
            ValidationError: If the amount is invalid.
            ConflictError: If the target category already has a budget in the
                target period.
        """
        with self._uow.session() as session:
            row = get_row(session, BudgetRow, budget_id, "budget")
            if not isinstance(amount, Unset):
                row.amount = _amount(amount)
            if not isinstance(category_id, Unset):
                row.category_id = get_row(
                    session, CategoryRow, category_id, "category"
                ).id
            if not isinstance(period_id, Unset):
                row.period_id = get_row(session, PeriodRow, period_id, "period").id
            duplicate = session.scalar(
                select(BudgetRow.id).where(
                    BudgetRow.category_id == row.category_id,
                    BudgetRow.period_id == row.period_id,
                    BudgetRow.id != row.id,
                )
            )
            if duplicate:
                raise ConflictError("the category already has a budget in this period")
            session.flush()
            return to_budget(row)

    def delete(self, budget_id: int) -> None:
        """Delete a budget.

        Raises:
            NotFoundError: If the budget does not exist.
        """
        with self._uow.session() as session:
            session.delete(get_row(session, BudgetRow, budget_id, "budget"))

    def copy(
        self, source_period_id: int, target_period_id: int, *, overwrite: bool = False
    ) -> builtins.list[Budget]:
        """Copy every budget of a period into another period.

        Args:
            source_period_id: Period to copy from.
            target_period_id: Period to copy to.
            overwrite: Whether to replace the amounts of budgets that already
                exist in the target period; otherwise they are kept.

        Returns:
            All budgets of the target period after the copy.

        Raises:
            NotFoundError: If a period does not exist.
            ValidationError: If both periods are the same.
        """
        if source_period_id == target_period_id:
            raise ValidationError("source and target periods must differ")
        with self._uow.session() as session:
            get_row(session, PeriodRow, source_period_id, "period")
            get_row(session, PeriodRow, target_period_id, "period")
            existing = {
                row.category_id: row
                for row in session.scalars(
                    select(BudgetRow).where(BudgetRow.period_id == target_period_id)
                )
            }
            for source in session.scalars(
                select(BudgetRow).where(BudgetRow.period_id == source_period_id)
            ).all():
                current = existing.get(source.category_id)
                if current is None:
                    session.add(
                        BudgetRow(
                            category_id=source.category_id,
                            period_id=target_period_id,
                            amount=source.amount,
                        )
                    )
                elif overwrite:
                    current.amount = source.amount
            session.flush()
            return self.list(period_id=target_period_id)

    def report(self, period_id: int) -> BudgetReport:
        """Compare each budget of a period with the actual external flows.

        Raises:
            NotFoundError: If the period does not exist.
        """
        with self._uow.session() as session:
            period = get_row(session, PeriodRow, period_id, "period")
            budgets = {
                row.category_id: row
                for row in session.scalars(
                    select(BudgetRow).where(BudgetRow.period_id == period_id)
                )
            }
            categories = ordered_categories(session)
            flows, _, _ = external_flows(session, period.start_date, period.end_date)
            totals = rollup(categories, flows)
            lines = []
            total_budget = total_actual = 0
            for category in categories:
                budget = budgets.get(category.id)
                if budget is None:
                    continue
                actual = totals[category.id]
                lines.append(
                    BudgetLine(
                        budget=to_budget(budget),
                        category=to_category(category),
                        actual=actual,
                        remaining=budget.amount + actual,
                    )
                )
                if category.parent_id is None or category.parent_id not in budgets:
                    total_budget += budget.amount
                    total_actual += actual
            return BudgetReport(
                period=to_period(period),
                lines=tuple(lines),
                total_budget=total_budget,
                total_actual=total_actual,
                total_remaining=total_budget + total_actual,
            )
