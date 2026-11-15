from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest

from picciuli import AccountType, Book, ConflictError, ImportSummary, ValidationError

from .conftest import d


@pytest.fixture
def source() -> Iterator[Book]:
    with Book.in_memory() as book:
        book.settings.update(currency="€", currency_code="EUR", cost_method="fifo")
        checking = book.accounts.create("Checking", AccountType.CHECKING)
        broker = book.accounts.create("Broker", AccountType.INVESTMENT)
        food = book.categories.create("Food")
        groceries = book.categories.create("Groceries", parent_id=food.id)
        etf = book.securities.create(
            "All-World", currency="USD", kind="etf", isin="IE00BK5BQT80"
        )
        book.securities.set_price(etf.id, d(2), Decimal("10.5"))
        book.securities.set_exchange_rate("USD", d(2), Decimal("0.9"))
        period = book.periods.create(d(1), end=d(31), name="January")
        book.budgets.create(groceries.id, period.id, 30000)
        book.transactions.record_income(d(1), 500000, account_id=checking.id)
        book.transactions.record_expense(
            d(3), 4500, account_id=checking.id, category_id=groceries.id
        )
        book.transactions.record_expense(
            d(3), 4500, account_id=checking.id, category_id=groceries.id
        )
        book.investments.record_buy(
            d(2),
            account_id=broker.id,
            security_id=etf.id,
            quantity=Decimal(2),
            cost=2100,
        )
        yield book


def _snapshot(book: Book) -> dict[str, object]:
    return {
        "accounts": [(a.name, a.type, a.position) for a in book.accounts.list()],
        "categories": [(c.name, c.parent_id is None) for c in book.categories.list()],
        "transactions": len(book.transactions.list()),
        "balances": {b.account.name: b.balance for b in book.accounts.balances()},
        "periods": [(p.name, p.start, p.end) for p in book.periods.list()],
        "budgets": [b.amount for b in book.budgets.list()],
        "securities": [s.name for s in book.securities.list()],
    }


def test_into_empty_book_copies_everything(book: Book, source: Book) -> None:
    summary = book.import_from(source)
    assert summary == ImportSummary(
        replaced=False,
        accounts=2,
        categories=2,
        securities=1,
        prices=1,
        exchange_rates=1,
        periods=1,
        budgets=1,
        transactions=4,
        duplicates=0,
    )
    assert _snapshot(book) == _snapshot(source)
    assert book.settings.get() == source.settings.get()
    etf = book.securities.list()[0]
    assert [p.price for p in book.securities.prices(etf.id)] == [Decimal("10.5")]
    assert len(book.securities.exchange_rates("USD")) == 1


def test_merging_twice_adds_nothing(book: Book, source: Book) -> None:
    book.import_from(source)
    summary = book.import_from(source)
    assert summary.duplicates == 4
    assert (summary.accounts, summary.transactions, summary.prices) == (0, 0, 0)
    assert _snapshot(book) == _snapshot(source)


def test_merge_reuses_matching_entities(book: Book, source: Book) -> None:
    book.settings.update(currency="EUR", currency_code="EUR")
    book.accounts.create("Wallet", AccountType.CASH)
    mine = book.accounts.create("checking", AccountType.SAVINGS)
    living = book.categories.create("Living")
    book.categories.create("food", parent_id=living.id)
    book.transactions.record_expense(d(9), 100, account_id=mine.id)

    summary = book.import_from(source)

    assert (summary.accounts, summary.categories) == (1, 1)
    assert [(a.name, a.type, a.position) for a in book.accounts.list()] == [
        ("Wallet", AccountType.CASH, 1),
        ("checking", AccountType.SAVINGS, 2),
        ("Broker", AccountType.INVESTMENT, 3),
    ]
    # "Groceries" belonged to "Food", a subcategory here: it joins its parent.
    groceries = next(c for c in book.categories.list() if c.name == "Groceries")
    assert groceries.parent_id == living.id
    assert len(book.transactions.list(account_id=mine.id)) == 4
    assert book.settings.get().currency == "EUR"
    assert book.settings.get().cost_method == "average"


def test_merge_rejects_other_currencies(book: Book, source: Book) -> None:
    book.accounts.create("Wallet", AccountType.CASH)
    with pytest.raises(ConflictError, match="EUR into a book in USD"):
        book.import_from(source)
    book.settings.update(currency_code="EUR", minor_digits=3)
    with pytest.raises(ConflictError, match="decimal digits"):
        book.import_from(source)
    assert [a.name for a in book.accounts.list()] == ["Wallet"]


def test_replace_erases_the_book_first(book: Book, source: Book) -> None:
    wallet = book.accounts.create("Wallet", AccountType.CASH)
    food = book.categories.create("Food")
    book.categories.create("Snacks", parent_id=food.id)
    book.transactions.record_expense(d(9), 100, account_id=wallet.id)
    book.periods.create(d(1, 2))

    summary = book.import_from(source, replace=True)

    assert summary.replaced and summary.transactions == 4
    assert _snapshot(book) == _snapshot(source)
    assert book.settings.get() == source.settings.get()


def test_cannot_import_itself(book: Book) -> None:
    with pytest.raises(ValidationError):
        book.import_from(book)
