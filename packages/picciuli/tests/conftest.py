from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest

from picciuli import Account, AccountType, Book, Category


def d(day: int, month: int = 1, year: int = 2025) -> dt.date:
    return dt.date(year, month, day)


@pytest.fixture
def book() -> Iterator[Book]:
    with Book.in_memory() as instance:
        yield instance


@pytest.fixture
def checking(book: Book) -> Account:
    return book.accounts.create("Checking", AccountType.CHECKING)


@pytest.fixture
def savings(book: Book) -> Account:
    return book.accounts.create("Savings", AccountType.SAVINGS)


@pytest.fixture
def card(book: Book) -> Account:
    return book.accounts.create("Card", AccountType.CREDIT_CARD)


@pytest.fixture
def food(book: Book) -> Category:
    return book.categories.create("Food")
