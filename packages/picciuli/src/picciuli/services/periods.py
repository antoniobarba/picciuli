"""Periods: named, possibly overlapping ranges of days, and their summaries."""

from __future__ import annotations

import builtins
import datetime as dt

from sqlalchemy import delete, or_, select

from picciuli import _validation as v
from picciuli._db.queries import (
    account_balances,
    external_flows,
    get_row,
    ordered_categories,
    rollup,
    to_account,
    to_category,
    to_period,
)
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import AccountRow, BudgetRow, PeriodRow
from picciuli.model import (
    UNSET,
    AccountChange,
    CategoryTotal,
    Period,
    PeriodSummary,
    Unset,
)

__all__ = ["PeriodService"]


def default_period_name(start: dt.date) -> str:
    """Return the default name of a period, for example `"January 2025"`."""
    return start.strftime("%B %Y")


class PeriodService:
    """Manage periods and summarize what happened during them.

    Obtain it as [`Book.periods`][picciuli.Book.periods].

    Periods are user-defined ranges of days (typically months or pay cycles) and
    may overlap. A period without an end day is *open-ended*: it lasts until a
    new open-ended period starts.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(
        self,
        start: dt.date,
        *,
        end: dt.date | None = None,
        name: str | None = None,
    ) -> Period:
        """Create a period.

        When the new period is open-ended, every earlier open-ended period is
        closed on the day before `start`, so that starting "the next month" ends
        the current one.

        Args:
            start: First day.
            end: Last day, or `None` for an open-ended period.
            name: Display name; defaults to the month and year of `start`.

        Raises:
            ValidationError: If an argument is invalid or `start` is after `end`.
        """
        start = v.date(start, "start")
        end = v.optional_date(end, "end")
        v.date_range(start, end)
        name = (
            default_period_name(start) if name is None else v.name(name, "period name")
        )
        with self._uow.session() as session:
            if end is None:
                open_periods = session.scalars(
                    select(PeriodRow).where(
                        PeriodRow.end_date.is_(None), PeriodRow.start_date < start
                    )
                )
                for existing in open_periods:
                    existing.end_date = start - dt.timedelta(days=1)
            row = PeriodRow(name=name, start_date=start, end_date=end)
            session.add(row)
            session.flush()
            return to_period(row)

    def get(self, period_id: int) -> Period:
        """Return a period.

        Raises:
            NotFoundError: If the period does not exist.
        """
        with self._uow.session() as session:
            return to_period(get_row(session, PeriodRow, period_id, "period"))

    def list(self) -> builtins.list[Period]:
        """Return all periods ordered by start day."""
        with self._uow.session() as session:
            rows = session.scalars(
                select(PeriodRow).order_by(PeriodRow.start_date, PeriodRow.id)
            )
            return [to_period(row) for row in rows]

    def periods_on(self, day: dt.date) -> builtins.list[Period]:
        """Return the periods containing a day, most recently started first.

        Raises:
            ValidationError: If `day` is not a date.
        """
        day = v.date(day, "day")
        with self._uow.session() as session:
            rows = session.scalars(
                select(PeriodRow)
                .where(
                    PeriodRow.start_date <= day,
                    or_(PeriodRow.end_date.is_(None), PeriodRow.end_date >= day),
                )
                .order_by(PeriodRow.start_date.desc(), PeriodRow.id.desc())
            )
            return [to_period(row) for row in rows]

    def update(
        self,
        period_id: int,
        *,
        name: str | Unset = UNSET,
        start: dt.date | Unset = UNSET,
        end: dt.date | None | Unset = UNSET,
    ) -> Period:
        """Change a period; arguments left `UNSET` are not modified.

        Other periods are never adjusted by an update.

        Raises:
            NotFoundError: If the period does not exist.
            ValidationError: If an argument is invalid or the start would be
                after the end.
        """
        with self._uow.session() as session:
            row = get_row(session, PeriodRow, period_id, "period")
            new_start = (
                row.start_date if isinstance(start, Unset) else v.date(start, "start")
            )
            new_end = (
                row.end_date if isinstance(end, Unset) else v.optional_date(end, "end")
            )
            v.date_range(new_start, new_end)
            if not isinstance(name, Unset):
                row.name = v.name(name, "period name")
            row.start_date = new_start
            row.end_date = new_end
            session.flush()
            return to_period(row)

    def delete(self, period_id: int) -> None:
        """Delete a period and its budgets. Transactions are not affected.

        Raises:
            NotFoundError: If the period does not exist.
        """
        with self._uow.session() as session:
            row = get_row(session, PeriodRow, period_id, "period")
            session.execute(delete(BudgetRow).where(BudgetRow.period_id == row.id))
            session.delete(row)

    def summary(self, period_id: int) -> PeriodSummary:
        """Summarize the external flows and account changes of a period.

        For an open-ended period, every transaction from its start day onwards
        is included, and closing balances include future-dated transactions.

        Raises:
            NotFoundError: If the period does not exist.
        """
        with self._uow.session() as session:
            row = get_row(session, PeriodRow, period_id, "period")
            start, end = row.start_date, row.end_date
            flows, income, expenses = external_flows(session, start, end)
            categories = ordered_categories(session)
            totals = rollup(categories, flows)
            category_totals = tuple(
                CategoryTotal(to_category(c), flows.get(c.id, 0), totals[c.id])
                for c in categories
            )
            opening = account_balances(session, until=start, inclusive=False)
            closing = account_balances(session, until=end)
            accounts = []
            for account in session.scalars(
                select(AccountRow).order_by(AccountRow.position, AccountRow.id)
            ):
                if account.closed_on is not None and account.closed_on < start:
                    continue
                if (
                    end is not None
                    and account.opening_date is not None
                    and account.opening_date > end
                ):
                    continue
                accounts.append(
                    AccountChange(
                        to_account(account), opening[account.id], closing[account.id]
                    )
                )
            return PeriodSummary(
                period=to_period(row),
                categories=category_totals,
                uncategorized=flows.get(None, 0),
                income=income,
                expenses=expenses,
                accounts=tuple(accounts),
            )
