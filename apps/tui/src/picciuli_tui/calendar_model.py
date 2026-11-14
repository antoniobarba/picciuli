"""Calendar logic of the overview, independent of the user interface."""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from picciuli import Book, Period, Transaction, TransactionKind

WEEKS = 6
"""The grid always shows six weeks so that its height never changes."""


@dataclass(frozen=True)
class DayFlow:
    """What happened on one day.

    Attributes:
        net: Sum of the external splits (income minus expenses).
        count: Number of transactions.
        transfers_only: Whether every transaction is a transfer.
    """

    net: int
    count: int
    transfers_only: bool


def month_grid(year: int, month: int) -> list[list[dt.date]]:
    """Return six Monday-first weeks covering a month.

    Days of the previous and next month fill the first and last weeks.
    """
    first = dt.date(year, month, 1)
    start = first - dt.timedelta(days=first.weekday())
    return [
        [start + dt.timedelta(days=week * 7 + day) for day in range(7)]
        for week in range(WEEKS)
    ]


def visible_range(year: int, month: int) -> tuple[dt.date, dt.date]:
    """Return the first and last day shown by `month_grid`."""
    grid = month_grid(year, month)
    return grid[0][0], grid[-1][-1]


def shift_month(day: dt.date, months: int) -> dt.date:
    """Move a day by whole months, clamping it to the length of the month."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return dt.date(year, month + 1, min(day.day, last))


def day_flows(transactions: Iterable[Transaction]) -> dict[dt.date, DayFlow]:
    """Aggregate transactions per day."""
    totals: dict[dt.date, tuple[int, int, bool]] = {}
    for transaction in transactions:
        net, count, transfers = totals.get(transaction.date, (0, 0, True))
        totals[transaction.date] = (
            net + transaction.net_amount,
            count + 1,
            transfers and transaction.kind is TransactionKind.TRANSFER,
        )
    return {day: DayFlow(*values) for day, values in totals.items()}


def load_month(book: Book, year: int, month: int) -> dict[dt.date, DayFlow]:
    """Return the flows of every day visible in the grid of a month."""
    start, end = visible_range(year, month)
    return day_flows(book.transactions.list(start=start, end=end))


def choose_period(covering: Sequence[Period], current_id: int | None) -> Period | None:
    """Pick the period to show for a day.

    Keep the current period while it covers the day; otherwise take the most
    recently started one. `covering` is ordered as returned by
    `PeriodService.periods_on` (most recently started first).
    """
    for period in covering:
        if period.id == current_id:
            return period
    return covering[0] if covering else None


def cycle_period(
    covering: Sequence[Period], current_id: int | None, step: int
) -> Period | None:
    """Move to the previous (`step=-1`) or next (`step=1`) covering period.

    Periods are cycled in chronological order and the cycle wraps around.
    """
    if not covering:
        return None
    ordered = list(reversed(covering))
    ids = [period.id for period in ordered]
    index = ids.index(current_id) if current_id in ids else len(ordered) - 1
    return ordered[(index + step) % len(ordered)]
