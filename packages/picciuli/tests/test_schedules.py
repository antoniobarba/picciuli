from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from picciuli import (
    Account,
    AccountSplit,
    AccountType,
    Book,
    Category,
    ConflictError,
    ExternalSplit,
    NotFoundError,
    Occurrence,
    ScheduleFrequency,
    ScheduleMode,
    TransactionKind,
    ValidationError,
)
from picciuli.services import schedules as schedules_module

from .conftest import d


def _rent(
    account: Account, category: Category | None = None
) -> list[AccountSplit | ExternalSplit]:
    return [
        AccountSplit(account.id, -80000),
        ExternalSplit(-80000, None if category is None else category.id),
    ]


def _dates(book: Book, schedule_id: int) -> list[dt.date]:
    return [t.date for t in book.transactions.list() if t.schedule_id == schedule_id]


class TestCreate:
    def test_defaults(self, book: Book, checking: Account, food: Category) -> None:
        schedule = book.schedules.create(
            d(31), _rent(checking, food), description=" Rent "
        )
        assert schedule.description == "Rent"
        assert schedule.frequency is ScheduleFrequency.MONTHLY
        assert (schedule.every, schedule.day_of_month) == (1, 31)
        assert (schedule.next_date, schedule.end, schedule.remaining) == (
            d(31),
            None,
            None,
        )
        assert schedule.mode is ScheduleMode.AUTO
        assert not schedule.paused and not schedule.is_finished
        assert schedule.kind is TransactionKind.EXPENSE
        assert schedule.net_amount == -80000
        assert book.schedules.get(schedule.id) == schedule
        assert book.schedules.list() == [schedule]

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"frequency": "hourly"}, "invalid frequency"),
            ({"mode": "maybe"}, "invalid mode"),
            ({"every": 0}, "every must be between"),
            ({"every": 1001}, "every must be between"),
            ({"day_of_month": 32}, "between 1 and 31"),
            ({"frequency": "weekly", "day_of_month": 3}, "only applies"),
            ({"occurrences": 0}, "at least 1"),
            ({"end": d(1)}, "start must be on or before end"),
        ],
    )
    def test_invalid_rule(
        self, book: Book, checking: Account, kwargs: dict[str, object], message: str
    ) -> None:
        with pytest.raises(ValidationError, match=message):
            book.schedules.create(d(2), _rent(checking), **kwargs)  # type: ignore[arg-type]
        assert book.schedules.list() == []

    def test_template_follows_transaction_rules(
        self, book: Book, checking: Account
    ) -> None:
        broker = book.accounts.create("Broker", AccountType.INVESTMENT)
        etf = book.securities.create("ETF", currency="USD")
        with pytest.raises(ValidationError, match="unbalanced"):
            book.schedules.create(
                d(1), [AccountSplit(checking.id, -1), ExternalSplit(-2)]
            )
        with pytest.raises(ValidationError, match="cannot move shares"):
            book.schedules.create(
                d(1),
                [
                    AccountSplit(checking.id, -100),
                    AccountSplit(broker.id, 100, None, etf.id, Decimal(1)),
                ],
            )
        with pytest.raises(NotFoundError):
            book.schedules.create(d(1), [AccountSplit(99, -1), ExternalSplit(-1)])
        book.accounts.close(checking.id, on=d(1))
        with pytest.raises(ConflictError, match="closed"):
            book.schedules.create(d(2), _rent(checking))


class TestOccurrences:
    def test_monthly_on_the_last_day(self, book: Book, checking: Account) -> None:
        schedule = book.schedules.create(d(31), _rent(checking))
        found = book.schedules.occurrences(d(1), d(31, 5))
        assert found == [
            Occurrence(schedule.id, day)
            for day in (d(31), d(28, 2), d(31, 3), d(30, 4), d(31, 5))
        ]

    def test_frequencies_and_limits(self, book: Book, checking: Account) -> None:
        weekly = book.schedules.create(
            d(3), _rent(checking), frequency="weekly", every=2, occurrences=3
        )
        daily = book.schedules.create(
            d(30), _rent(checking), frequency="daily", end=d(2, 2)
        )
        quarterly = book.schedules.create(d(15), _rent(checking), every=3)
        paused = book.schedules.create(d(1), _rent(checking), frequency="daily")
        book.schedules.update(paused.id, paused=True)

        found = book.schedules.occurrences(d(1), d(31, 12))
        by_schedule: dict[int, list[dt.date]] = {}
        for occurrence in found:
            by_schedule.setdefault(occurrence.schedule_id, []).append(occurrence.date)
        assert by_schedule[weekly.id] == [d(3), d(17), d(31)]
        assert by_schedule[daily.id] == [d(30), d(31), d(1, 2), d(2, 2)]
        assert by_schedule[quarterly.id] == [d(15), d(15, 4), d(15, 7), d(15, 10)]
        assert paused.id not in by_schedule
        assert found == sorted(found, key=lambda o: (o.date, o.schedule_id))

    def test_yearly_on_the_29th_of_february(
        self, book: Book, checking: Account
    ) -> None:
        yearly = book.schedules.create(
            dt.date(2024, 2, 29), _rent(checking), frequency=ScheduleFrequency.YEARLY
        )
        found = book.schedules.occurrences(dt.date(2026, 1, 1), dt.date(2028, 1, 10))
        assert [o.date for o in found] == [dt.date(2026, 2, 28), dt.date(2027, 2, 28)]
        leap = book.schedules.occurrences(dt.date(2028, 1, 1), dt.date(2028, 12, 31))
        assert leap == [Occurrence(yearly.id, dt.date(2028, 2, 29))]

    def test_range_starting_long_after_the_next_occurrence(
        self, book: Book, checking: Account
    ) -> None:
        first = dt.date(2000, 1, 1)
        daily = book.schedules.create(
            first, _rent(checking), frequency="daily", occurrences=9500
        )
        monthly = book.schedules.create(dt.date(2000, 1, 31), _rent(checking))
        found = book.schedules.occurrences(d(1, 1, 2026), d(10, 1, 2026))
        last = first + dt.timedelta(days=9499)
        assert [o.date for o in found if o.schedule_id == daily.id] == [
            d(day, 1, 2026) for day in range(1, last.day + 1)
        ]
        assert not [o for o in found if o.schedule_id == monthly.id]
        later = book.schedules.occurrences(d(1, 2, 2026), d(28, 2, 2026))
        assert later == [Occurrence(monthly.id, d(28, 2, 2026))]

    def test_range_is_limited(self, book: Book) -> None:
        with pytest.raises(ValidationError, match="longer than"):
            book.schedules.occurrences(d(1), d(1, 1, 2028))
        with pytest.raises(ValidationError):
            book.schedules.occurrences(d(2), d(1))


class TestCatchUp:
    def test_records_automatic_occurrences_once(
        self, book: Book, checking: Account, food: Category
    ) -> None:
        rent = book.schedules.create(
            d(31, 12, 2024), _rent(checking, food), description="Rent", notes="flat"
        )
        result = book.schedules.catch_up(d(28, 2))
        assert [t.date for t in result.posted] == [
            d(31, 12, 2024),
            d(31),
            d(28, 2),
        ]
        first = result.posted[0]
        assert (first.description, first.notes, first.schedule_id) == (
            "Rent",
            "flat",
            rent.id,
        )
        assert first.splits == tuple(_rent(checking, food))
        assert (result.due, result.failed) == ((), ())
        assert book.schedules.get(rent.id).next_date == d(31, 3)
        assert book.accounts.balance(checking.id) == -240000

        again = book.schedules.catch_up(d(28, 2))
        assert (again.posted, again.due, again.failed) == ((), (), ())

    def test_lists_occurrences_waiting_for_confirmation(
        self, book: Book, checking: Account
    ) -> None:
        bill = book.schedules.create(d(10), _rent(checking), mode="confirm")
        result = book.schedules.catch_up(d(15, 3))
        assert result.posted == ()
        assert result.due == tuple(
            Occurrence(bill.id, day) for day in (d(10), d(10, 2), d(10, 3))
        )
        assert book.transactions.list() == []
        assert book.schedules.get(bill.id).next_date == d(10)

    def test_failures_are_flagged_and_do_not_stop_the_others(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        broken = book.schedules.create(d(5), _rent(savings), description="Gym")
        fine = book.schedules.create(d(6), _rent(checking))
        book.accounts.close(savings.id, on=d(1))

        result = book.schedules.catch_up(d(6, 2))

        assert [t.schedule_id for t in result.posted] == [fine.id, fine.id]
        (failed,) = result.failed
        assert failed.id == broken.id
        assert failed.last_error is not None and "closed" in failed.last_error
        assert book.schedules.get(broken.id).next_date == d(5)
        skipped = book.schedules.skip(broken.id)
        assert (skipped.next_date, skipped.last_error) == (d(5, 2), None)

    def test_paused_schedules_wait(self, book: Book, checking: Account) -> None:
        schedule = book.schedules.create(d(1), _rent(checking))
        book.schedules.update(schedule.id, paused=True)
        assert book.schedules.catch_up(d(1, 6)).posted == ()
        book.schedules.update(schedule.id, paused=False)
        assert len(book.schedules.catch_up(d(1, 6)).posted) == 6

    def test_finishes_after_the_last_occurrence(
        self, book: Book, checking: Account
    ) -> None:
        counted = book.schedules.create(d(1), _rent(checking), occurrences=2)
        ending = book.schedules.create(d(1), _rent(checking), end=d(15, 2))
        result = book.schedules.catch_up(d(1, 12))
        assert len(result.posted) == 4
        for schedule_id in (counted.id, ending.id):
            schedule = book.schedules.get(schedule_id)
            assert schedule.is_finished
        assert book.schedules.get(counted.id).remaining == 0
        assert book.schedules.list()[-1].is_finished

    def test_is_limited_per_call(
        self, book: Book, checking: Account, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(schedules_module, "MAX_CATCH_UP", 3)
        auto = book.schedules.create(d(1), _rent(checking), frequency="daily")
        confirm = book.schedules.create(
            d(1), _rent(checking), frequency="daily", mode="confirm"
        )
        result = book.schedules.catch_up(d(31))
        assert len(result.posted) == 3 and len(result.due) == 3
        assert book.schedules.get(auto.id).next_date == d(4)
        assert len(book.schedules.catch_up(d(31)).posted) == 3
        assert book.schedules.get(confirm.id).next_date == d(1)

    def test_rejects_invalid_day(self, book: Book) -> None:
        with pytest.raises(ValidationError):
            book.schedules.catch_up("2025-01-01")  # type: ignore[arg-type]


class TestPostAndSkip:
    def test_post_with_a_different_amount(
        self, book: Book, checking: Account, food: Category
    ) -> None:
        bill = book.schedules.create(
            d(10), _rent(checking, food), mode="confirm", description="Power"
        )
        posted = book.schedules.post(
            bill.id,
            date=d(12),
            splits=[AccountSplit(checking.id, -9150), ExternalSplit(-9150, food.id)],
            notes="estimated",
        )
        assert (posted.date, posted.description, posted.notes) == (
            d(12),
            "Power",
            "estimated",
        )
        assert posted.net_amount == -9150
        updated = book.schedules.get(bill.id)
        assert updated.next_date == d(10, 2)
        assert updated.splits == tuple(_rent(checking, food))
        default = book.schedules.post(bill.id)
        assert (default.date, default.net_amount) == (d(10, 2), -80000)

    def test_post_validates_the_override(self, book: Book, checking: Account) -> None:
        bill = book.schedules.create(d(10), _rent(checking))
        with pytest.raises(ValidationError, match="unbalanced"):
            book.schedules.post(bill.id, splits=[AccountSplit(checking.id, -1)])
        assert book.schedules.get(bill.id).next_date == d(10)

    def test_finished_schedules_cannot_post_or_skip(
        self, book: Book, checking: Account
    ) -> None:
        once = book.schedules.create(d(1), _rent(checking), occurrences=1)
        assert book.schedules.skip(once.id).is_finished
        with pytest.raises(ConflictError, match="finished"):
            book.schedules.post(once.id)
        with pytest.raises(ConflictError, match="finished"):
            book.schedules.skip(once.id)
        assert book.transactions.list() == []
        with pytest.raises(NotFoundError):
            book.schedules.skip(99)


class TestUpdateAndDelete:
    def test_update_rule(self, book: Book, checking: Account, food: Category) -> None:
        schedule = book.schedules.create(d(10), _rent(checking), frequency="weekly")
        assert schedule.day_of_month is None
        monthly = book.schedules.update(
            schedule.id, frequency="monthly", next_date=d(20)
        )
        assert (monthly.day_of_month, monthly.next_date) == (20, d(20))
        last_day = book.schedules.update(schedule.id, day_of_month=31)
        assert last_day.day_of_month == 31
        assert book.schedules.update(schedule.id, frequency="yearly").day_of_month == 31
        daily = book.schedules.update(
            schedule.id,
            frequency="daily",
            every=3,
            mode="confirm",
            description="Changed",
            notes="n",
            occurrences=5,
            end=d(30, 6),
            splits=_rent(checking, food),
        )
        assert (daily.day_of_month, daily.every, daily.mode) == (
            None,
            3,
            ScheduleMode.CONFIRM,
        )
        assert (daily.description, daily.notes, daily.remaining) == ("Changed", "n", 5)
        assert daily.splits == tuple(_rent(checking, food))

    def test_update_checks_consistency(self, book: Book, checking: Account) -> None:
        schedule = book.schedules.create(d(10), _rent(checking), occurrences=1)
        with pytest.raises(ValidationError, match="after the end day"):
            book.schedules.update(schedule.id, end=d(5))
        with pytest.raises(ValidationError, match="paused must be"):
            book.schedules.update(schedule.id, paused=1)  # type: ignore[arg-type]
        assert book.schedules.skip(schedule.id).is_finished
        assert book.schedules.update(schedule.id, frequency="weekly").is_finished
        with pytest.raises(ValidationError, match="day of month is needed"):
            book.schedules.update(schedule.id, frequency="monthly")
        with pytest.raises(ValidationError, match="at least 1"):
            book.schedules.update(schedule.id, next_date=d(1, 3))
        restarted = book.schedules.update(
            schedule.id, next_date=d(1, 3), occurrences=None
        )
        assert restarted.next_date == d(1, 3) and restarted.remaining is None

    def test_update_clears_the_last_error(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        schedule = book.schedules.create(d(5), _rent(savings))
        book.accounts.close(savings.id, on=d(1))
        book.schedules.catch_up(d(5))
        assert book.schedules.get(schedule.id).last_error is not None
        fixed = book.schedules.update(schedule.id, splits=_rent(checking))
        assert fixed.last_error is None
        assert len(book.schedules.catch_up(d(5)).posted) == 1

    def test_delete_keeps_the_transactions(self, book: Book, checking: Account) -> None:
        schedule = book.schedules.create(d(1), _rent(checking))
        book.schedules.catch_up(d(1, 2))
        assert _dates(book, schedule.id) == [d(1), d(1, 2)]
        book.schedules.delete(schedule.id)
        assert book.schedules.list() == []
        assert [t.schedule_id for t in book.transactions.list()] == [None, None]
        with pytest.raises(NotFoundError):
            book.schedules.delete(schedule.id)

    def test_accounts_and_categories_in_templates(
        self, book: Book, checking: Account, food: Category
    ) -> None:
        other = book.categories.create("Other")
        schedule = book.schedules.create(
            d(1), _rent(checking, food), description="Rent"
        )
        with pytest.raises(ConflictError, match="'Rent'"):
            book.accounts.delete(checking.id)
        book.categories.delete(food.id, reassign_to=other.id)
        assert book.schedules.get(schedule.id).splits[1] == ExternalSplit(
            -80000, other.id
        )
        book.categories.delete(other.id)
        assert book.schedules.get(schedule.id).splits[1] == ExternalSplit(-80000)
        book.schedules.delete(schedule.id)
        book.accounts.delete(checking.id)
