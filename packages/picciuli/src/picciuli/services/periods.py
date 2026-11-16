"""Periods: named, possibly overlapping ranges of days, and their summaries."""

from __future__ import annotations

import builtins
import datetime as dt

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from picciuli import _calendar
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
from picciuli.errors import ValidationError
from picciuli.limits import MAX_GENERATED_PERIODS
from picciuli.model import (
    UNSET,
    AccountChange,
    CategoryTotal,
    Period,
    PeriodChange,
    PeriodChangeKind,
    PeriodSummary,
    Unset,
)
from picciuli.services.settings import read_settings

__all__ = ["PeriodService"]


def default_period_name(start: dt.date) -> str:
    """Return the default name of a period, for example `"January 2025"`."""
    return start.strftime("%B %Y")


def _period_index(day: dt.date, start_day: int, shift: bool) -> int:
    try:
        return _calendar.period_index(day, start_day, shift)
    except OverflowError:
        raise ValidationError("today is out of the supported range of dates") from None


def _add_generated(
    session: Session, start: dt.date, end: dt.date, name: str
) -> PeriodRow:
    """Add a monthly period after the existing ones, with their budgets."""
    previous = session.scalars(
        select(PeriodRow)
        .where(PeriodRow.start_date < start)
        .order_by(PeriodRow.start_date.desc(), PeriodRow.id.desc())
        .limit(1)
    ).first()
    for open_period in session.scalars(
        select(PeriodRow).where(
            PeriodRow.end_date.is_(None), PeriodRow.start_date < start
        )
    ):
        open_period.end_date = start - dt.timedelta(days=1)
    row = PeriodRow(name=name, start_date=start, end_date=end)
    session.add(row)
    session.flush()
    if previous is not None:
        for budget in session.scalars(
            select(BudgetRow).where(BudgetRow.period_id == previous.id)
        ).all():
            session.add(
                BudgetRow(
                    category_id=budget.category_id,
                    period_id=row.id,
                    amount=budget.amount,
                )
            )
        session.flush()
    return row


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

    def ensure_monthly(self, today: dt.date) -> builtins.list[Period]:
        """Create the monthly periods missing up to the one containing `today`.

        It does nothing unless
        [`Settings.period_start_day`][picciuli.model.Settings] is set. A book
        without periods gets the current monthly period only. Otherwise every
        monthly period starting after the most recent period is created, up
        to the current one and at most
        [`MAX_GENERATED_PERIODS`][picciuli.limits.MAX_GENERATED_PERIODS] of
        them. Each new period copies the budgets of the period before it and
        ends the open-ended periods that started earlier.

        Args:
            today: The current day of the user.

        Returns:
            The periods created, by start day.

        Raises:
            ValidationError: If `today` is not a date or is out of range.
        """
        today = v.date(today, "today")
        with self._uow.session() as session:
            settings = read_settings(session)
            start_day = settings.period_start_day
            if start_day is None:
                return []
            shift = settings.period_weekend_shift
            current = _period_index(today, start_day, shift)
            last_start = session.scalar(select(func.max(PeriodRow.start_date)))
            first = current
            if last_start is not None:
                try:
                    first = _calendar.period_index(last_start, start_day, shift) + 1
                except OverflowError:
                    first = current
                first = max(first, current - MAX_GENERATED_PERIODS + 1)
            created = []
            for index in range(first, current + 1):
                start, end, name = _calendar.monthly_period(index, start_day, shift)
                if last_start is None or start > last_start:
                    created.append(_add_generated(session, start, end, name))
            return [to_period(row) for row in created]

    def regenerate(
        self, today: dt.date, *, dry_run: bool = False
    ) -> builtins.list[PeriodChange]:
        """Align existing periods with the monthly period settings.

        Every monthly period from the one containing the start of the oldest
        period up to the one containing `today` (at most
        [`MAX_GENERATED_PERIODS`][picciuli.limits.MAX_GENERATED_PERIODS]) is
        matched with an existing period: first one with exactly its days, else
        the one whose middle day it contains. That period gets its dates and
        name, and keeps its budgets. Monthly periods without a match are
        created. Existing periods matching a monthly period that is already
        taken, or outside that range, are left alone. Nothing is ever deleted.

        Args:
            today: The current day of the user.
            dry_run: Only return the changes, without applying them.

        Returns:
            The changes, by start day; periods already aligned are omitted.

        Raises:
            ValidationError: If monthly periods are off, or `today` is not a
                date or is out of range.
        """
        today = v.date(today, "today")
        with self._uow.session() as session:
            settings = read_settings(session)
            start_day = settings.period_start_day
            if start_day is None:
                raise ValidationError("monthly periods are off")
            shift = settings.period_weekend_shift
            current = _period_index(today, start_day, shift)
            rows = session.scalars(
                select(PeriodRow).order_by(PeriodRow.start_date, PeriodRow.id)
            ).all()
            if not rows:
                return []
            try:
                first = _calendar.period_index(rows[0].start_date, start_day, shift)
            except OverflowError:
                first = current
            first = max(first, current - MAX_GENERATED_PERIODS + 1)
            slots = {
                index: _calendar.monthly_period(index, start_day, shift)
                for index in range(first, current + 1)
            }
            # Periods that already have the right days keep them, so that a
            # misaligned period never moves onto a monthly period that exists.
            by_days: dict[tuple[dt.date, dt.date | None], int] = {
                (start, end): index for index, (start, end, _) in slots.items()
            }
            owner: dict[int, int] = {}
            for row in rows:
                index = by_days.get((row.start_date, row.end_date))
                if index is not None:
                    owner.setdefault(index, row.id)
            changes: builtins.list[PeriodChange] = []
            for row in rows:
                index = by_days.get((row.start_date, row.end_date))
                if index is None or owner[index] != row.id:
                    middle = row.start_date
                    if row.end_date is not None:
                        middle += (row.end_date - row.start_date) // 2
                    try:
                        index = _calendar.period_index(middle, start_day, shift)
                    except OverflowError:
                        continue
                    if index not in slots:
                        continue
                    if index in owner:
                        changes.append(
                            PeriodChange(
                                PeriodChangeKind.KEEP,
                                to_period(row),
                                row.name,
                                row.start_date,
                                row.end_date,
                            )
                        )
                        continue
                    owner[index] = row.id
                start, end, name = slots[index]
                if (row.start_date, row.end_date, row.name) == (start, end, name):
                    continue
                changes.append(
                    PeriodChange(
                        PeriodChangeKind.UPDATE, to_period(row), name, start, end
                    )
                )
                if not dry_run:
                    row.start_date, row.end_date, row.name = start, end, name
            for index, (start, end, name) in slots.items():
                if index not in owner:
                    changes.append(
                        PeriodChange(PeriodChangeKind.CREATE, None, name, start, end)
                    )
                    if not dry_run:
                        session.add(
                            PeriodRow(name=name, start_date=start, end_date=end)
                        )
            session.flush()
            changes.sort(key=lambda c: (c.start, c.period.id if c.period else 0))
            return changes

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
