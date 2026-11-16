"""Date arithmetic of recurring transactions and monthly periods (private)."""

from __future__ import annotations

import calendar
import datetime as dt
from collections.abc import Iterator

from picciuli.model import ScheduleFrequency

_SATURDAY = 5
_FRIDAY = 4


def month_length(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def month_index(day: dt.date) -> int:
    """Months since year 0: consecutive months have consecutive indexes."""
    return day.year * 12 + day.month - 1


def add_months(day: dt.date, months: int, day_of_month: int) -> dt.date | None:
    """`day` moved by `months`, on `day_of_month` or the last day of shorter months.

    Returns `None` outside the range of `datetime.date`.
    """
    year, month = divmod(month_index(day) + months, 12)
    if not dt.MINYEAR <= year <= dt.MAXYEAR:
        return None
    return dt.date(year, month + 1, min(day_of_month, month_length(year, month + 1)))


def following(
    day: dt.date,
    frequency: ScheduleFrequency,
    every: int,
    day_of_month: int | None,
) -> dt.date | None:
    """The occurrence after `day`, or `None` past the end of the calendar."""
    if frequency in (ScheduleFrequency.DAILY, ScheduleFrequency.WEEKLY):
        days = every * (7 if frequency is ScheduleFrequency.WEEKLY else 1)
        try:
            return day + dt.timedelta(days=days)
        except OverflowError:
            return None
    months = every * (12 if frequency is ScheduleFrequency.YEARLY else 1)
    return add_months(day, months, day_of_month or day.day)


def occurrences(
    first: dt.date | None,
    frequency: ScheduleFrequency,
    every: int,
    day_of_month: int | None,
    *,
    end: dt.date | None = None,
    remaining: int | None = None,
) -> Iterator[dt.date]:
    """Every occurrence from `first`, until `end` or `remaining` are exhausted."""
    day = first
    left = remaining
    while (
        day is not None and (end is None or day <= end) and (left is None or left > 0)
    ):
        yield day
        if left is not None:
            left -= 1
        day = following(day, frequency, every, day_of_month)


def skip_before(
    first: dt.date,
    frequency: ScheduleFrequency,
    every: int,
    day_of_month: int | None,
    start: dt.date,
) -> tuple[dt.date | None, int]:
    """Jump close to `start` without stepping through every occurrence.

    Returns an occurrence on or before `start` (or `first` itself when it
    is not before `start`) and how many occurrences were skipped to reach it.
    """
    if first >= start:
        return first, 0
    if frequency in (ScheduleFrequency.DAILY, ScheduleFrequency.WEEKLY):
        step = every * (7 if frequency is ScheduleFrequency.WEEKLY else 1)
        skipped = (start - first).days // step
        return first + dt.timedelta(days=skipped * step), skipped
    step = every * (12 if frequency is ScheduleFrequency.YEARLY else 1)
    skipped = max(0, (month_index(start) - month_index(first)) // step - 1)
    if skipped == 0:
        return first, 0
    return add_months(first, skipped * step, day_of_month or first.day), skipped


def payday(year: int, month: int, start_day: int, weekend_shift: bool) -> dt.date:
    """First day of the monthly period of `month`."""
    day = dt.date(year, month, min(start_day, month_length(year, month)))
    if weekend_shift and day.weekday() >= _SATURDAY:
        day -= dt.timedelta(days=day.weekday() - _FRIDAY)
    return day


def monthly_period(
    index: int, start_day: int, weekend_shift: bool
) -> tuple[dt.date, dt.date, str]:
    """First day, last day and name of the monthly period starting in month `index`.

    The period is named after the month it covers most (the later one on a
    tie), for example "November 2026" from 27 October to 26 November.

    Raises:
        OverflowError: Near the limits of `datetime.date`.
    """
    year, month = divmod(index, 12)
    next_year, next_month = divmod(index + 1, 12)
    if not (year > dt.MINYEAR and next_year < dt.MAXYEAR):
        raise OverflowError("date out of range")
    start = payday(year, month + 1, start_day, weekend_shift)
    end = payday(next_year, next_month + 1, start_day, weekend_shift) - dt.timedelta(
        days=1
    )
    best: tuple[int, int] = (0, 0)
    for candidate in range(month_index(start), month_index(end) + 1):
        y, m = divmod(candidate, 12)
        first = max(start, dt.date(y, m + 1, 1))
        last = min(end, dt.date(y, m + 1, month_length(y, m + 1)))
        best = max(best, ((last - first).days + 1, candidate))
    y, m = divmod(best[1], 12)
    return start, end, dt.date(y, m + 1, 1).strftime("%B %Y")


def period_index(day: dt.date, start_day: int, weekend_shift: bool) -> int:
    """Month index of the monthly period containing `day`.

    Raises:
        OverflowError: Near the limits of `datetime.date`.
    """
    index = month_index(day)
    for candidate in (index - 1, index, index + 1):
        start, end, _ = monthly_period(candidate, start_day, weekend_shift)
        if start <= day <= end:
            return candidate
    raise AssertionError("unreachable: consecutive periods leave no gaps")
