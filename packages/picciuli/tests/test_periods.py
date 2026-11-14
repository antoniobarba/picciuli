from __future__ import annotations

import pytest

from picciuli import (
    Account,
    AccountSplit,
    AccountType,
    Book,
    Category,
    ExternalSplit,
    NotFoundError,
    Period,
    ValidationError,
)

from .conftest import d


class TestCrud:
    def test_create_defaults_and_get(self, book: Book) -> None:
        period = book.periods.create(d(1))
        assert period == Period(id=period.id, name="January 2025", start=d(1), end=None)
        assert book.periods.get(period.id) == period
        named = book.periods.create(d(1, 8), end=d(15, 8), name=" Holiday ")
        assert (named.name, named.start, named.end) == ("Holiday", d(1, 8), d(15, 8))

    def test_new_open_period_closes_previous_open_ones(self, book: Book) -> None:
        january = book.periods.create(d(1))
        holiday = book.periods.create(d(10), end=d(20), name="Trip")
        assert book.periods.get(january.id).end is None
        february = book.periods.create(d(1, 2))
        assert book.periods.get(january.id).end == d(31)
        assert book.periods.get(holiday.id).end == d(20)
        assert book.periods.get(february.id).end is None
        assert [p.id for p in book.periods.list()] == [
            january.id,
            holiday.id,
            february.id,
        ]

    def test_update(self, book: Book) -> None:
        period = book.periods.create(d(1))
        updated = book.periods.update(period.id, name="Jan", end=d(31))
        assert (updated.name, updated.start, updated.end) == ("Jan", d(1), d(31))
        assert book.periods.update(period.id, start=d(2)).start == d(2)
        assert book.periods.update(period.id, end=None).end is None
        with pytest.raises(ValidationError, match="on or before"):
            book.periods.update(period.id, start=d(5), end=d(4))
        with pytest.raises(ValidationError, match="empty"):
            book.periods.update(period.id, name=" ")

    def test_validation_and_missing(self, book: Book) -> None:
        with pytest.raises(ValidationError, match="on or before"):
            book.periods.create(d(2), end=d(1))
        with pytest.raises(ValidationError):
            book.periods.create("2025-01-01")  # type: ignore[arg-type]
        with pytest.raises(NotFoundError):
            book.periods.get(1)

    def test_delete_removes_budgets(self, book: Book, food: Category) -> None:
        period = book.periods.create(d(1))
        book.budgets.create(food.id, period.id, 100)
        book.periods.delete(period.id)
        assert book.periods.list() == []
        assert book.budgets.list() == []

    def test_periods_on(self, book: Book) -> None:
        january = book.periods.create(d(1), end=d(31))
        trip = book.periods.create(d(10), end=d(20), name="Trip")
        open_ended = book.periods.create(d(15))
        assert [p.id for p in book.periods.periods_on(d(16))] == [
            open_ended.id,
            trip.id,
            january.id,
        ]
        assert [p.id for p in book.periods.periods_on(d(5))] == [january.id]
        assert book.periods.periods_on(d(1, 1, 2024)) == []
        assert trip.contains(d(10)) and trip.contains(d(20))
        assert not trip.contains(d(21))
        assert open_ended.contains(d(1, 1, 2030))


class TestSummary:
    def test_summary(
        self,
        book: Book,
        checking: Account,
        savings: Account,
        card: Account,
        food: Category,
    ) -> None:
        groceries = book.categories.create("Groceries", parent_id=food.id)
        salary = book.categories.create("Salary")
        old = book.accounts.create("Old", AccountType.CASH)
        book.accounts.close(old.id, on=d(1, 12, 2024))
        future = book.accounts.create("Future", AccountType.CASH, opening_date=d(1, 3))
        book.accounts.update(checking.id, opening_balance=1000)
        period = book.periods.create(d(1), end=d(31))

        book.transactions.record_income(d(31, 12, 2024), 999, account_id=checking.id)
        book.transactions.record_income(
            d(1), 3000, account_id=checking.id, category_id=salary.id
        )
        book.transactions.record_expense(
            d(2), 100, account_id=checking.id, category_id=food.id
        )
        book.transactions.record_expense(
            d(3), 250, account_id=card.id, category_id=groceries.id
        )
        book.transactions.create(
            d(4),
            [AccountSplit(checking.id, -20), ExternalSplit(-30), ExternalSplit(10)],
        )
        book.transactions.record_transfer(
            d(5), 500, from_account_id=checking.id, to_account_id=savings.id
        )
        book.transactions.record_expense(d(1, 2), 7, account_id=checking.id)

        summary = book.periods.summary(period.id)
        assert summary.period == period
        assert [(c.category.name, c.amount, c.total) for c in summary.categories] == [
            ("Food", -100, -350),
            ("Groceries", -250, -250),
            ("Salary", 3000, 3000),
        ]
        assert summary.uncategorized == -20
        assert (summary.income, summary.expenses) == (3010, -380)
        assert summary.net == 2630
        changes = {c.account.name: (c.opening, c.closing) for c in summary.accounts}
        assert changes == {
            "Checking": (1999, 1999 + 3000 - 100 - 20 - 500),
            "Savings": (0, 500),
            "Card": (0, -250),
        }
        checking_change = next(
            c for c in summary.accounts if c.account.id == checking.id
        )
        assert checking_change.change == 2380
        assert old.id not in {c.account.id for c in summary.accounts}
        assert future.id not in {c.account.id for c in summary.accounts}

    def test_open_ended_summary_includes_everything_after_start(
        self, book: Book, checking: Account
    ) -> None:
        period = book.periods.create(d(1))
        book.transactions.record_expense(d(1, 6), 5, account_id=checking.id)
        summary = book.periods.summary(period.id)
        assert (summary.expenses, summary.uncategorized) == (-5, -5)
        assert summary.accounts[0].closing == -5

    def test_missing_period(self, book: Book) -> None:
        with pytest.raises(NotFoundError):
            book.periods.summary(1)
