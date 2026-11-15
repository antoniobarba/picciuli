from __future__ import annotations

from decimal import Decimal

import pytest

from picciuli import (
    Account,
    Book,
    Budget,
    Category,
    ConflictError,
    CostMethod,
    NotFoundError,
    Period,
    Settings,
    ValidationError,
)

from .conftest import d


@pytest.fixture
def january(book: Book) -> Period:
    return book.periods.create(d(1), end=d(31))


@pytest.fixture
def february(book: Book) -> Period:
    return book.periods.create(d(1, 2), end=d(28, 2))


class TestCrud:
    def test_create_get_list(
        self, book: Book, food: Category, january: Period, february: Period
    ) -> None:
        budget = book.budgets.create(food.id, january.id, 500)
        assert budget == Budget(budget.id, food.id, january.id, 500)
        assert book.budgets.get(budget.id) == budget
        other = book.budgets.create(food.id, february.id, 0)
        assert book.budgets.list() == [budget, other]
        assert book.budgets.list(period_id=february.id) == [other]
        assert book.budgets.list(category_id=food.id, period_id=january.id) == [budget]

    def test_create_rules(self, book: Book, food: Category, january: Period) -> None:
        book.budgets.create(food.id, january.id, 500)
        with pytest.raises(ConflictError, match="already has a budget"):
            book.budgets.create(food.id, january.id, 100)
        with pytest.raises(ValidationError, match="negative"):
            book.budgets.create(food.id, january.id, -1)
        with pytest.raises(ValidationError, match="integer"):
            book.budgets.create(food.id, january.id, 1.0)  # type: ignore[arg-type]
        with pytest.raises(NotFoundError, match="category"):
            book.budgets.create(99, january.id, 1)
        with pytest.raises(NotFoundError, match="period"):
            book.budgets.create(food.id, 99, 1)

    def test_update_and_delete(
        self, book: Book, food: Category, january: Period, february: Period
    ) -> None:
        home = book.categories.create("Home")
        budget = book.budgets.create(food.id, january.id, 500)
        book.budgets.create(home.id, february.id, 1)
        updated = book.budgets.update(budget.id, amount=700, category_id=home.id)
        assert (updated.amount, updated.category_id) == (700, home.id)
        with pytest.raises(ConflictError):
            book.budgets.update(budget.id, period_id=february.id)
        assert book.budgets.get(budget.id) == updated
        with pytest.raises(NotFoundError):
            book.budgets.update(budget.id, category_id=99)
        book.budgets.delete(budget.id)
        with pytest.raises(NotFoundError):
            book.budgets.get(budget.id)

    def test_copy(
        self, book: Book, food: Category, january: Period, february: Period
    ) -> None:
        home = book.categories.create("Home")
        book.budgets.create(food.id, january.id, 500)
        book.budgets.create(home.id, january.id, 900)
        existing = book.budgets.create(food.id, february.id, 1)
        copied = book.budgets.copy(january.id, february.id)
        assert {(b.category_id, b.amount) for b in copied} == {
            (food.id, 1),
            (home.id, 900),
        }
        book.budgets.copy(january.id, february.id, overwrite=True)
        assert book.budgets.get(existing.id).amount == 500
        with pytest.raises(ValidationError, match="differ"):
            book.budgets.copy(january.id, january.id)
        with pytest.raises(NotFoundError):
            book.budgets.copy(january.id, 99)


class TestReport:
    def test_report_rolls_up_and_avoids_double_counting(
        self,
        book: Book,
        checking: Account,
        savings: Account,
        food: Category,
        january: Period,
    ) -> None:
        groceries = book.categories.create("Groceries", parent_id=food.id)
        fun = book.categories.create("Fun")
        book.transactions.record_expense(
            d(2), 100, account_id=checking.id, category_id=food.id
        )
        book.transactions.record_expense(
            d(3), 300, account_id=checking.id, category_id=groceries.id
        )
        book.transactions.record_income(
            d(4), 50, account_id=checking.id, category_id=groceries.id
        )
        book.transactions.record_expense(
            d(5), 80, account_id=checking.id, category_id=fun.id
        )
        book.transactions.record_transfer(
            d(5), 999, from_account_id=checking.id, to_account_id=savings.id
        )
        book.transactions.record_expense(
            d(1, 2), 5000, account_id=checking.id, category_id=fun.id
        )
        book.budgets.create(groceries.id, january.id, 200)
        book.budgets.create(fun.id, january.id, 100)
        book.budgets.create(food.id, january.id, 600)

        report = book.budgets.report(january.id)
        assert report.period == january
        assert [
            (line.category.name, line.budget.amount, line.actual, line.remaining)
            for line in report.lines
        ] == [
            ("Food", 600, -350, 250),
            ("Groceries", 200, -250, -50),
            ("Fun", 100, -80, 20),
        ]
        assert (report.total_budget, report.total_actual, report.total_remaining) == (
            700,
            -430,
            270,
        )

    def test_empty_report_and_missing_period(self, book: Book, january: Period) -> None:
        report = book.budgets.report(january.id)
        assert (report.lines, report.total_budget, report.total_remaining) == ((), 0, 0)
        with pytest.raises(NotFoundError):
            book.budgets.report(99)


class TestSettings:
    def test_defaults_and_update(self, book: Book) -> None:
        usd = Settings("$", 2, "USD")
        assert book.settings.get() == usd
        assert usd.cost_method is CostMethod.AVERAGE
        assert usd.price_provider == "yahoo"
        assert book.settings.update(currency=" € ") == Settings("€", 2, "USD")
        assert book.settings.update(minor_digits=0) == Settings("€", 0, "USD")
        assert book.settings.get() == Settings("€", 0, "USD")

    def test_investment_settings(self, book: Book) -> None:
        book.securities.set_exchange_rate("GBP", d(1), Decimal("1.1"))
        updated = book.settings.update(
            currency_code=" eur ", cost_method="fifo", price_provider="yahoo"
        )
        assert updated.currency_code == "EUR"
        assert updated.cost_method is CostMethod.FIFO
        # Rates were relative to the old book currency.
        assert book.securities.exchange_rates("GBP") == []
        book.securities.set_exchange_rate("GBP", d(1), Decimal("1.2"))
        book.settings.update(currency_code="EUR")
        assert len(book.securities.exchange_rates("GBP")) == 1
        assert book.settings.update(currency_code=None).currency_code is None

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"currency": ""},
            {"minor_digits": 7},
            {"minor_digits": "2"},
            {"currency_code": "EURO"},
            {"currency_code": 1},
            {"cost_method": "lifo"},
            {"price_provider": "nowhere"},
        ],
    )
    def test_invalid(self, book: Book, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            book.settings.update(**kwargs)  # type: ignore[arg-type]
        assert book.settings.get() == Settings("$", 2, "USD")
