from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from picciuli import (
    AccountSplit,
    AccountType,
    Book,
    Category,
    ExternalSplit,
    Period,
    Settings,
)
from picciuli_tui.formatting import (
    MoneyFormat,
    account_change,
    category_label,
    category_tree_label,
    percent_text,
    period_range,
    price_text,
    progress_bar,
    quantity_text,
    transaction_accounts,
    transaction_category,
    transaction_title,
)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "+0"),
        (-4530, "-45"),
        (250, "+2.5"),
        (-99_950, "-1k"),
        (-99_949, "-999"),
        (245_000, "+2.5k"),
        (1_234_500, "+12k"),
        (-999_960_00, "-1M"),
        (123_456_789_00, "+123M"),
        (1_234_567_890_00, "+1.2G"),
        (999_999_999_999_00, "+1000G"),
    ],
)
def test_compact(amount: int, expected: str) -> None:
    assert MoneyFormat().compact(amount) == expected


def test_compact_without_minor_digits_rounds_to_units() -> None:
    assert MoneyFormat("¥", 0).compact(7) == "+7"


def test_money_format_from_settings() -> None:
    money = MoneyFormat.from_settings(Settings(currency="EUR", minor_digits=3))
    assert money.amount(-1_234_500) == "-EUR 1,234.500"
    assert money.amount(5, currency=False, plus=True) == "+0.005"
    assert money.plain(-1_234_500) == "-1234.500"
    assert money.parse("1,000") == 1_000_000


def test_category_labels() -> None:
    parent = Category(1, "Food", "F", None, 1)
    child = Category(2, "Groceries", "G", 1, 1)
    orphan = Category(3, "Odd", "O", 99, 1)
    categories = {c.id: c for c in (parent, child, orphan)}
    assert category_label(None, categories) == "Uncategorized"
    assert category_label(1, categories) == "Food"
    assert category_label(2, categories) == "Food › Groceries"
    assert category_label(3, categories) == "Odd"
    assert category_label(42, categories) == "#42"
    assert category_tree_label(parent) == "Food"
    assert category_tree_label(child) == "  └ Groceries"


def test_period_range() -> None:
    assert period_range(Period(1, "P", dt.date(2025, 1, 27), None)) == (
        "27 Jan 2025 – open"
    )
    assert period_range(Period(1, "P", dt.date(2025, 1, 1), dt.date(2025, 1, 31))) == (
        "01 Jan 2025 – 31 Jan 2025"
    )


def test_transaction_labels(book: Book) -> None:
    checking = book.accounts.create("Checking", AccountType.CHECKING)
    savings = book.accounts.create("Savings", AccountType.SAVINGS)
    food = book.categories.create("Food")
    home = book.categories.create("Home")
    accounts = {a.id: a for a in book.accounts.list()}
    categories = {c.id: c for c in book.categories.list()}
    day = dt.date(2025, 1, 2)
    transfer = book.transactions.record_transfer(
        day, 100, from_account_id=checking.id, to_account_id=savings.id
    )
    assert transaction_accounts(transfer, accounts) == "Checking → Savings"
    assert transaction_category(transfer, categories) == "Transfer"
    assert transaction_title(transfer) == "(transfer)"
    expense = book.transactions.record_expense(
        day, 100, account_id=checking.id, category_id=food.id, description="Shop"
    )
    assert transaction_accounts(expense, accounts) == "Checking"
    assert transaction_category(expense, categories) == "Food"
    assert transaction_title(expense) == "Shop"
    split = book.transactions.create(
        day,
        [
            AccountSplit(checking.id, -100),
            ExternalSplit(-60, food.id),
            ExternalSplit(-40, home.id),
        ],
    )
    assert transaction_category(split, categories) == "Split (2)"
    assert account_change(split, checking.id) == -100
    assert transaction_accounts(split, {}) == f"#{checking.id}"


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [(-1.0, "░░░░"), (0.5, "██░░"), (2.0, "████")],
)
def test_progress_bar(fraction: float, expected: str) -> None:
    assert progress_bar(fraction, width=4) == expected


def test_investment_formatting() -> None:
    assert quantity_text(Decimal("1234.5000")) == "1,234.5"
    assert quantity_text(Decimal(3)) == "3"
    assert price_text(Decimal("169.8"), "EUR") == "169.80 EUR"
    assert price_text(Decimal("0.123456"), "USD") == "0.123456 USD"
    assert price_text(Decimal("1200"), "USD") == "1,200.00 USD"
    assert percent_text(50, 1000) == "+5.0%"
    assert percent_text(-50, 1000) == "-5.0%"
    assert percent_text(5, 0) == ""
