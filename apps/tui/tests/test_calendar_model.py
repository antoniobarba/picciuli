from __future__ import annotations

import datetime as dt

from picciuli import Account, Book, Period
from picciuli_tui.calendar_model import (
    DayFlow,
    choose_period,
    cycle_period,
    load_month,
    month_grid,
    shift_month,
    visible_range,
)


def test_month_grid_is_six_monday_first_weeks_with_adjacent_days() -> None:
    grid = month_grid(2025, 3)
    assert len(grid) == 6
    assert all(len(week) == 7 for week in grid)
    assert grid[0][0] == dt.date(2025, 2, 24)
    assert all(week[0].weekday() == 0 for week in grid)
    assert grid[-1][-1] == dt.date(2025, 4, 6)
    assert visible_range(2025, 3) == (dt.date(2025, 2, 24), dt.date(2025, 4, 6))


def test_month_grid_starting_on_monday() -> None:
    assert month_grid(2024, 7)[0][0] == dt.date(2024, 7, 1)


def test_shift_month_clamps_the_day() -> None:
    assert shift_month(dt.date(2025, 1, 31), 1) == dt.date(2025, 2, 28)
    assert shift_month(dt.date(2024, 3, 31), -1) == dt.date(2024, 2, 29)
    assert shift_month(dt.date(2025, 12, 15), 1) == dt.date(2026, 1, 15)
    assert shift_month(dt.date(2025, 1, 15), -13) == dt.date(2023, 12, 15)


def test_load_month_aggregates_days(
    book: Book, checking: Account, savings: Account
) -> None:
    day = dt.date(2025, 3, 3)
    book.transactions.record_expense(day, 500, account_id=checking.id)
    book.transactions.record_income(day, 200, account_id=checking.id)
    book.transactions.record_transfer(
        day + dt.timedelta(days=1),
        100,
        from_account_id=checking.id,
        to_account_id=savings.id,
    )
    book.transactions.record_expense(dt.date(2025, 2, 24), 7, account_id=checking.id)
    book.transactions.record_expense(dt.date(2025, 2, 23), 9, account_id=checking.id)
    flows = load_month(book, 2025, 3)
    assert flows == {
        day: DayFlow(net=-300, count=2, transfers_only=False),
        day + dt.timedelta(days=1): DayFlow(net=0, count=1, transfers_only=True),
        dt.date(2025, 2, 24): DayFlow(net=-7, count=1, transfers_only=False),
    }


def _periods() -> list[Period]:
    # As returned by periods_on: most recently started first.
    return [
        Period(3, "Holiday", dt.date(2025, 3, 5), dt.date(2025, 3, 9)),
        Period(2, "March", dt.date(2025, 2, 27), None),
        Period(1, "Quarter", dt.date(2025, 1, 1), dt.date(2025, 3, 31)),
    ]


def test_choose_period_keeps_the_current_one() -> None:
    covering = _periods()
    assert choose_period(covering, 1) == covering[2]
    assert choose_period(covering, 99) == covering[0]
    assert choose_period(covering, None) == covering[0]
    assert choose_period([], 1) is None


def test_cycle_period_is_chronological_and_wraps() -> None:
    covering = _periods()
    assert cycle_period(covering, 3, 1) == covering[2]
    assert cycle_period(covering, 1, 1) == covering[1]
    assert cycle_period(covering, 1, -1) == covering[0]
    assert cycle_period(covering, None, -1) == covering[1]
    assert cycle_period([], None, 1) is None
