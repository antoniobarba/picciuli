from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable, Iterator

import pytest
from textual.pilot import Pilot

from picciuli import Account, AccountType, Book, Category
from picciuli_tui.app import PicciuliApp
from picciuli_tui.formatting import MoneyFormat

TODAY = dt.date(2025, 3, 12)

Scenario = Callable[[PicciuliApp, Pilot[None]], Awaitable[None]]


@pytest.fixture
def book() -> Iterator[Book]:
    with Book.in_memory() as instance:
        yield instance


@pytest.fixture
def money() -> MoneyFormat:
    return MoneyFormat()


@pytest.fixture
def checking(book: Book) -> Account:
    return book.accounts.create("Checking", AccountType.CHECKING)


@pytest.fixture
def savings(book: Book) -> Account:
    return book.accounts.create("Savings", AccountType.SAVINGS)


@pytest.fixture
def food(book: Book) -> Category:
    return book.categories.create("Food")


def run_app(
    book: Book, scenario: Scenario, *, size: tuple[int, int] = (150, 45)
) -> None:
    """Run the application headless and play a scenario against it."""

    async def main() -> None:
        app = PicciuliApp(book, name="test.db", today=lambda: TODAY)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await scenario(app, pilot)

    asyncio.run(main())
