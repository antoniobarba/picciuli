"""History: cash flows and balances month by month or period by period."""

from __future__ import annotations

import builtins
import calendar
import datetime as dt
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._db.queries import account_balances, external_flows, ordered_categories
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import AccountRow, PeriodRow
from picciuli.errors import ValidationError
from picciuli.limits import MAX_HISTORY_POINTS
from picciuli.model import (
    AccountClass,
    AccountType,
    HistoryBalance,
    HistoryFlow,
    HistoryPoint,
)
from picciuli.services.investments import _market_data, _valuation

__all__ = ["HistoryService"]


def _count(value: object) -> int:
    result = v.integer(value, "count")
    if not 1 <= result <= MAX_HISTORY_POINTS:
        raise ValidationError(f"count must be between 1 and {MAX_HISTORY_POINTS}")
    return result


class HistoryService:
    """Follow income, expenses, spending and balances over time.

    Obtain it as [`Book.history`][picciuli.Book.history].

    Each [`HistoryPoint`][picciuli.HistoryPoint] covers a calendar month or a
    period: its cash flows by category, and every account balance at its end
    with investments at market value, so net worth, debts and savings can be
    charted. A month or period still running stops at the current day.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def months(
        self, count: int = 12, *, offset: int = 0, today: dt.date | None = None
    ) -> builtins.list[HistoryPoint]:
        """Return `count` calendar months, oldest first.

        Args:
            count: Number of months, from 1 to 120.
            offset: Number of months to skip back: `0` ends with the
                current month, `12` with the same month a year earlier.
            today: The current day; defaults to the actual date.

        Raises:
            ValidationError: If `count` or `offset` is out of range.
        """
        count = _count(count)
        offset = v.count(offset, "offset")
        today = v.optional_date(today, "today") or dt.date.today()
        last = today.year * 12 + today.month - 1 - offset
        first = last - count + 1
        if first < 12:
            raise ValidationError("offset goes back before year 1")
        ranges = []
        for index in range(first, last + 1):
            year, month = divmod(index, 12)
            start = dt.date(year, month + 1, 1)
            end = start.replace(day=calendar.monthrange(year, month + 1)[1])
            ranges.append((start, end, None))
        return self._points(ranges, today)

    def periods(
        self, count: int = 12, *, offset: int = 0, today: dt.date | None = None
    ) -> builtins.list[HistoryPoint]:
        """Return up to `count` periods started on or before today, oldest first.

        Periods are ordered by their first day; they may overlap, and an
        open-ended period runs until today.

        Args:
            count: Number of periods, from 1 to 120.
            offset: Number of the most recent periods to skip.
            today: The current day; defaults to the actual date.

        Raises:
            ValidationError: If `count` or `offset` is out of range.
        """
        count = _count(count)
        offset = v.count(offset, "offset")
        today = v.optional_date(today, "today") or dt.date.today()
        with self._uow.session() as session:
            rows = builtins.list(
                session.scalars(
                    select(PeriodRow)
                    .where(PeriodRow.start_date <= today)
                    .order_by(PeriodRow.start_date, PeriodRow.id)
                )
            )
        stop = len(rows) - offset
        chosen = rows[max(stop - count, 0) : max(stop, 0)]
        return self._points(
            [(row.start_date, row.end_date, row.id) for row in chosen], today
        )

    def _points(
        self,
        ranges: Sequence[tuple[dt.date, dt.date | None, int | None]],
        today: dt.date,
    ) -> builtins.list[HistoryPoint]:
        with self._uow.session() as session:
            accounts = builtins.list(
                session.scalars(
                    select(AccountRow).order_by(AccountRow.position, AccountRow.id)
                )
            )
            order = [c.id for c in ordered_categories(session)]
            return [
                _point(session, accounts, order, start, end, period_id, today)
                for start, end, period_id in ranges
            ]


def _point(
    session: Session,
    accounts: Sequence[AccountRow],
    order: Sequence[int],
    start: dt.date,
    end: dt.date | None,
    period_id: int | None,
    today: dt.date,
) -> HistoryPoint:
    partial = end is None or end > today
    last = today if end is None or end > today else end
    flows, income, expenses = external_flows(session, start, last)
    ordered = [*order, None]
    settings, prices, rates = _market_data(session, last)
    ledger = account_balances(session, until=last)
    balances = []
    assets = liabilities = 0
    for row in accounts:
        balance = ledger[row.id]
        value = balance
        if row.type == AccountType.INVESTMENT.value:
            value = _valuation(session, row, last, settings, prices, rates).market_value
        if balance == 0 and value == 0:
            continue
        balances.append(HistoryBalance(row.id, balance, value))
        if AccountType(row.type).account_class is AccountClass.LIABILITY:
            liabilities += value
        else:
            assets += value
    return HistoryPoint(
        start=start,
        end=last,
        period_id=period_id,
        partial=partial,
        income=income,
        expenses=expenses,
        flows=tuple(
            HistoryFlow(category_id, flows[category_id])
            for category_id in ordered
            if flows.get(category_id)
        ),
        balances=tuple(balances),
        assets=assets,
        liabilities=liabilities,
    )
