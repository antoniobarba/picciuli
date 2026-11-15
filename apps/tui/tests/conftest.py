from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from textual.pilot import Pilot

from picciuli import Account, AccountType, Book, Category, ValidationError
from picciuli.errors import PriceProviderError
from picciuli.prices import PricePoint, PriceProvider, Quote, SecurityInfo
from picciuli_tui.app import PicciuliApp
from picciuli_tui.formatting import MoneyFormat

TODAY = dt.date(2025, 3, 12)

Scenario = Callable[[PicciuliApp, Pilot[None]], Awaitable[None]]


class FakeProvider(PriceProvider):
    """Offline prices in euros, for interface tests."""

    id = "fake"
    name = "Fake quotes"
    description = "Prices for tests"

    def __init__(self) -> None:
        self.prices: dict[str, Decimal] = {}
        self.history_starts: list[dt.date] = []
        self.broken = False

    def latest(self, symbol: str) -> Quote:
        if self.broken:
            raise ValidationError("provider exploded")
        if symbol not in self.prices:
            raise PriceProviderError(f"unknown symbol {symbol}")
        moment = dt.datetime(2025, 3, 12, 17, tzinfo=dt.timezone.utc)
        return Quote(symbol, self.prices[symbol], "EUR", moment)

    def history(self, symbol: str, start: dt.date, end: dt.date) -> list[PricePoint]:
        self.history_starts.append(start)
        return [PricePoint(start, self.prices[symbol])]

    def search(self, query: str) -> list[SecurityInfo]:
        if query == "nothing":
            return []
        return [SecurityInfo("VWCE.DE", "Vanguard FTSE All-World", "XETRA", "ETF")]


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
    book: Book,
    scenario: Scenario,
    *,
    size: tuple[int, int] = (150, 45),
    **options: Any,
) -> None:
    """Run the application headless and play a scenario against it."""

    async def main() -> None:
        app = PicciuliApp(book, name="test.db", today=lambda: TODAY, **options)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await scenario(app, pilot)

    asyncio.run(main())
