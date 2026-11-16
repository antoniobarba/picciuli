from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from picciuli import (
    Account,
    AccountType,
    Book,
    Category,
    HistoryBalance,
    HistoryFlow,
    ValidationError,
)

from .conftest import d


class TestMonths:
    def test_flows_and_balances_month_by_month(
        self, book: Book, checking: Account, card: Account, food: Category
    ) -> None:
        salary = book.categories.create("Salary")
        groceries = book.categories.create("Groceries", parent_id=food.id)
        book.transactions.record_income(d(31, 12, 2024), 1000, account_id=checking.id)
        book.transactions.record_income(
            d(5), 2000, account_id=checking.id, category_id=salary.id
        )
        book.transactions.record_expense(
            d(10), 300, account_id=card.id, category_id=groceries.id
        )
        book.transactions.record_expense(d(11), 50, account_id=checking.id)
        book.transactions.record_transfer(
            d(28), 300, from_account_id=checking.id, to_account_id=card.id
        )
        book.transactions.record_expense(
            d(3, 2), 100, account_id=checking.id, category_id=food.id
        )
        # Future-dated, after the current day: not counted yet.
        book.transactions.record_expense(d(20, 2), 999, account_id=checking.id)

        jan, feb = book.history.months(2, today=d(15, 2))

        assert (jan.start, jan.end, jan.partial, jan.period_id) == (
            d(1),
            d(31),
            False,
            None,
        )
        assert (jan.income, jan.expenses) == (2000, -350)
        assert jan.flows == (
            HistoryFlow(groceries.id, -300),
            HistoryFlow(salary.id, 2000),
            HistoryFlow(None, -50),
        )
        assert jan.balances == (HistoryBalance(checking.id, 2650, 2650),)
        assert (jan.assets, jan.liabilities, jan.net_worth) == (2650, 0, 2650)

        assert (feb.start, feb.end, feb.partial) == (d(1, 2), d(15, 2), True)
        assert (feb.income, feb.expenses) == (0, -100)
        assert feb.flows == (HistoryFlow(food.id, -100),)
        assert feb.net_worth == 2550

    def test_liabilities_and_offset(self, book: Book, checking: Account) -> None:
        loan = book.accounts.create(
            "Loan", AccountType.LOAN, opening_balance=-5000, opening_date=d(1, 11, 2024)
        )
        book.transactions.record_transfer(
            d(5), 1000, from_account_id=checking.id, to_account_id=loan.id
        )

        nov, dec = book.history.months(2, offset=2, today=d(15, 2))

        assert (nov.start, dec.end) == (d(1, 11, 2024), d(31, 12, 2024))
        assert dec.balances == (HistoryBalance(loan.id, -5000, -5000),)
        assert (dec.assets, dec.liabilities) == (0, -5000)
        jan = book.history.months(1, offset=1, today=d(15, 2))[0]
        assert jan.balances == (
            HistoryBalance(checking.id, -1000, -1000),
            HistoryBalance(loan.id, -4000, -4000),
        )
        assert (jan.assets, jan.liabilities) == (-1000, -4000)

    def test_investments_at_market_value_on_each_day(
        self, book: Book, checking: Account
    ) -> None:
        broker = book.accounts.create("Broker", AccountType.INVESTMENT)
        etf = book.securities.create("ETF", currency="EUR")
        book.transactions.record_income(d(1), 10000, account_id=checking.id)
        book.investments.record_buy(
            d(2),
            account_id=broker.id,
            security_id=etf.id,
            quantity=Decimal(10),
            cost=4000,
            from_account_id=checking.id,
        )

        # No price yet: valued at cost.
        jan = book.history.months(1, today=d(31))[0]
        assert HistoryBalance(broker.id, 4000, 4000) in jan.balances

        book.securities.set_price(etf.id, d(10, 2), Decimal(5))
        book.securities.set_exchange_rate("EUR", d(10, 2), Decimal("0.9"))
        book.securities.set_price(etf.id, d(10, 3), Decimal(6))
        jan, feb, mar = book.history.months(3, today=d(31, 3))
        assert HistoryBalance(broker.id, 4000, 4000) in jan.balances
        assert HistoryBalance(broker.id, 4000, 4500) in feb.balances
        assert HistoryBalance(broker.id, 4000, 5400) in mar.balances
        assert mar.net_worth == 6000 + 5400

    @pytest.mark.parametrize(
        ("count", "offset"), [(0, 0), (121, 0), (1, -1), (12, 2025 * 12)]
    )
    def test_rejects_bad_ranges(self, book: Book, count: int, offset: int) -> None:
        with pytest.raises(ValidationError):
            book.history.months(count, offset=offset, today=d(1))


class TestPeriods:
    def test_latest_periods_started_by_today(
        self, book: Book, checking: Account
    ) -> None:
        first = book.periods.create(d(1), end=d(31), name="January")
        holiday = book.periods.create(d(20), end=d(25), name="Holiday")
        current = book.periods.create(d(1, 2), name="Open")
        book.periods.create(d(1, 3), end=d(31, 3), name="Future")
        book.transactions.record_income(d(22), 100, account_id=checking.id)
        book.transactions.record_income(d(2, 2), 10, account_id=checking.id)

        points = book.history.periods(today=d(15, 2))

        assert [p.period_id for p in points] == [first.id, holiday.id, current.id]
        assert [p.income for p in points] == [100, 100, 10]
        assert [(p.end, p.partial) for p in points] == [
            (d(31), False),
            (d(25), False),
            (d(15, 2), True),
        ]
        assert [p.period_id for p in book.history.periods(2, today=d(15, 2))] == [
            holiday.id,
            current.id,
        ]
        older = book.history.periods(2, offset=2, today=d(15, 2))
        assert [p.period_id for p in older] == [first.id]
        assert book.history.periods(offset=5, today=d(15, 2)) == []

    def test_period_ending_after_today_is_partial(self, book: Book) -> None:
        book.periods.create(d(1), end=d(31))
        (point,) = book.history.periods(today=d(10))
        assert (point.end, point.partial) == (d(10), True)


def test_defaults_to_the_actual_date(book: Book) -> None:
    points = book.history.months()
    assert len(points) == 12
    assert points[-1].end == dt.date.today()
