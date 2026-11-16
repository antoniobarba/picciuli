"""Date arithmetic of recurring transactions and monthly periods."""

from __future__ import annotations

import datetime as dt
import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from picciuli import _calendar as c
from picciuli.model import ScheduleFrequency

days = st.dates(min_value=dt.date(1900, 1, 1), max_value=dt.date(2200, 12, 31))
frequencies = st.sampled_from(ScheduleFrequency)


@given(
    first=days,
    frequency=frequencies,
    every=st.integers(1, 30),
    day_of_month=st.integers(1, 31),
    start=days,
)
def test_skip_before_lands_on_an_occurrence(
    first: dt.date,
    frequency: ScheduleFrequency,
    every: int,
    day_of_month: int,
    start: dt.date,
) -> None:
    dom = day_of_month if frequency in ("monthly", "yearly") else None
    moved, skipped = c.skip_before(first, frequency, every, dom, start)
    assert moved is not None
    assert moved == first or moved <= start
    walked = c.occurrences(first, frequency, every, dom)
    assert next(itertools.islice(walked, skipped, None)) == moved


@given(
    first=days,
    frequency=frequencies,
    every=st.integers(1, 12),
    day_of_month=st.integers(1, 31),
)
def test_occurrences_increase_and_respect_the_day_of_month(
    first: dt.date, frequency: ScheduleFrequency, every: int, day_of_month: int
) -> None:
    dom = day_of_month if frequency in ("monthly", "yearly") else None
    found = list(itertools.islice(c.occurrences(first, frequency, every, dom), 30))
    assert found[0] == first
    assert found == sorted(set(found))
    if dom is not None:
        for day in found[1:]:
            assert day.day == min(dom, c.month_length(day.year, day.month))


def test_occurrences_stop_at_the_limits() -> None:
    monthly = ScheduleFrequency.MONTHLY
    assert list(
        c.occurrences(dt.date(2025, 1, 31), monthly, 1, 31, end=dt.date(2025, 4, 29))
    ) == [dt.date(2025, 1, 31), dt.date(2025, 2, 28), dt.date(2025, 3, 31)]
    assert list(
        c.occurrences(
            dt.date(2025, 1, 1), ScheduleFrequency.DAILY, 1, None, remaining=2
        )
    ) == [dt.date(2025, 1, 1), dt.date(2025, 1, 2)]
    assert list(c.occurrences(dt.date.max, ScheduleFrequency.WEEKLY, 1, None)) == [
        dt.date.max
    ]
    assert list(c.occurrences(dt.date(9999, 12, 1), monthly, 1, 1)) == [
        dt.date(9999, 12, 1)
    ]


@given(day=days, start_day=st.integers(1, 31), shift=st.booleans())
def test_monthly_periods_tile_the_calendar(
    day: dt.date, start_day: int, shift: bool
) -> None:
    index = c.period_index(day, start_day, shift)
    start, end, name = c.monthly_period(index, start_day, shift)
    assert start <= day <= end
    following, _, _ = c.monthly_period(index + 1, start_day, shift)
    assert following == end + dt.timedelta(days=1)
    if shift:
        assert start.weekday() < 5
    named = dt.datetime.strptime(name, "%B %Y").date()
    in_named = sum(
        1
        for offset in range((end - start).days + 1)
        if (start + dt.timedelta(days=offset)).month == named.month
    )
    assert in_named * 2 >= (end - start).days + 1


@pytest.mark.parametrize(
    ("start_day", "shift", "expected"),
    [
        (27, True, (dt.date(2026, 10, 27), dt.date(2026, 11, 26), "November 2026")),
        (1, False, (dt.date(2026, 11, 1), dt.date(2026, 11, 30), "November 2026")),
        # 1 November 2026 is a Sunday: the period starts on Friday 30 October.
        (1, True, (dt.date(2026, 10, 30), dt.date(2026, 11, 30), "November 2026")),
        (10, False, (dt.date(2026, 11, 10), dt.date(2026, 12, 9), "November 2026")),
        (31, False, (dt.date(2026, 10, 31), dt.date(2026, 11, 29), "November 2026")),
    ],
)
def test_monthly_period_examples(
    start_day: int, shift: bool, expected: tuple[dt.date, dt.date, str]
) -> None:
    index = c.period_index(dt.date(2026, 11, 20), start_day, shift)
    assert c.monthly_period(index, start_day, shift) == expected


def test_monthly_periods_near_the_limits_of_dates() -> None:
    with pytest.raises(OverflowError):
        c.period_index(dt.date(1, 1, 15), 1, False)
    with pytest.raises(OverflowError):
        c.period_index(dt.date(9999, 12, 15), 1, False)
