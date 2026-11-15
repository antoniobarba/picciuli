"""The price provider interface and its data types."""

from __future__ import annotations

import abc
import datetime as dt
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "CachingProvider",
    "PricePoint",
    "PriceProvider",
    "Quote",
    "SecurityInfo",
]


@dataclass(frozen=True, slots=True)
class Quote:
    """The latest known price of a symbol.

    Attributes:
        symbol: The provider symbol that was quoted.
        price: Price of one unit in major units of `currency`.
        currency: ISO 4217 code of the price, or `None` if the provider does
            not say.
        time: When the price was observed, preferably in the exchange's time
            zone, so that `time.date()` is the trading day.
        name: Display name of the instrument, if the provider gives one.
    """

    symbol: str
    price: Decimal
    currency: str | None
    time: dt.datetime
    name: str | None = None

    @property
    def date(self) -> dt.date:
        """Trading day of the quote."""
        return self.time.date()


@dataclass(frozen=True, slots=True)
class PricePoint:
    """A daily closing price.

    Attributes:
        date: Trading day.
        price: Closing price in major units.
    """

    date: dt.date
    price: Decimal


@dataclass(frozen=True, slots=True)
class SecurityInfo:
    """A search result: an instrument known to a provider.

    Attributes:
        symbol: Provider symbol, to be stored as the `symbol` of a
            [`Security`][picciuli.model.Security].
        name: Display name.
        exchange: Exchange or market name, if known.
        kind: Instrument type as reported by the provider (for example
            `"ETF"`), if known.
        currency: ISO 4217 code of the price, if known.
    """

    symbol: str
    name: str
    exchange: str | None = None
    kind: str | None = None
    currency: str | None = None


class PriceProvider(abc.ABC):
    """A source of security prices and exchange rates.

    Implementations only need [`latest`][picciuli.prices.PriceProvider.latest]
    and [`history`][picciuli.prices.PriceProvider.history]; the other methods
    have conservative defaults. Every method that fails raises
    [`PriceProviderError`][picciuli.errors.PriceProviderError].

    Providers must not touch the network until a method is called, must be
    constructible without arguments (the registry does so), and must be safe to
    call from a worker thread.

    The class attributes `id`, `name` and `description` identify the provider
    in the [registry][picciuli.prices.register_provider] and in user interfaces.
    """

    id: str
    """Stable identifier stored in the book settings, for example `"yahoo"`."""
    name: str
    """Human-readable name."""
    description: str = ""
    """One-line description for user interfaces."""

    @abc.abstractmethod
    def latest(self, symbol: str) -> Quote:
        """Return the latest price of a symbol.

        Raises:
            PriceProviderError: If no price is available.
        """

    @abc.abstractmethod
    def history(self, symbol: str, start: dt.date, end: dt.date) -> list[PricePoint]:
        """Return daily closing prices from `start` to `end` (inclusive).

        Raises:
            PriceProviderError: If the history is not available.
        """

    def exchange_rate_symbol(self, currency: str, base: str) -> str | None:
        """Return the symbol quoting one unit of `currency` in `base`.

        `latest` and `history` of that symbol give exchange rates. The default
        returns `None`: the provider cannot convert currencies.
        """
        return None

    def search(self, query: str) -> list[SecurityInfo]:
        """Find instruments by name, symbol or ISIN. The default finds nothing.

        Raises:
            PriceProviderError: If the search fails.
        """
        return []


class CachingProvider(PriceProvider):
    """Wrap a provider and reuse its latest quotes for a while.

    User interfaces that refresh frequently can use it to avoid hammering the
    data source: a quote younger than `ttl` seconds is returned from memory.
    At most `max_size` symbols are kept; the least recently used are dropped.

    Args:
        provider: The provider to wrap.
        ttl: How long a quote stays fresh, in seconds.
        clock: Monotonic clock (injectable for tests).
        max_size: Largest number of cached quotes.
    """

    def __init__(
        self,
        provider: PriceProvider,
        *,
        ttl: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_size: int = 1024,
    ) -> None:
        self.provider = provider
        self.id = provider.id
        self.name = provider.name
        self.description = provider.description
        self.ttl = ttl
        self.max_size = max_size
        self._clock = clock
        self._lock = threading.Lock()
        self._quotes: OrderedDict[str, tuple[float, Quote]] = OrderedDict()

    def latest(self, symbol: str) -> Quote:
        """Return a cached quote if still fresh, otherwise ask the provider."""
        now = self._clock()
        with self._lock:
            cached = self._quotes.get(symbol)
            if cached is not None and now - cached[0] < self.ttl:
                self._quotes.move_to_end(symbol)
                return cached[1]
        quote = self.provider.latest(symbol)
        with self._lock:
            self._quotes[symbol] = (now, quote)
            self._quotes.move_to_end(symbol)
            while len(self._quotes) > self.max_size:
                self._quotes.popitem(last=False)
        return quote

    def history(self, symbol: str, start: dt.date, end: dt.date) -> list[PricePoint]:
        """Delegate to the wrapped provider (not cached)."""
        return self.provider.history(symbol, start, end)

    def exchange_rate_symbol(self, currency: str, base: str) -> str | None:
        """Delegate to the wrapped provider."""
        return self.provider.exchange_rate_symbol(currency, base)

    def search(self, query: str) -> list[SecurityInfo]:
        """Delegate to the wrapped provider (not cached)."""
        return self.provider.search(query)
