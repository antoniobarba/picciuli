"""The exchange-rate provider interface and its data types."""

from __future__ import annotations

import abc
import datetime as dt
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

__all__ = ["CachingRateProvider", "ExchangeRateProvider", "RatePoint", "RateQuote"]


@dataclass(frozen=True, slots=True)
class RateQuote:
    """The latest known exchange rate of a currency pair.

    Attributes:
        currency: ISO 4217 code of the currency being converted.
        base: ISO 4217 code of the target currency.
        rate: Units of `base` for one unit of `currency`.
        time: When the rate was observed; `time.date()` is the day it is
            stored under.
    """

    currency: str
    base: str
    rate: Decimal
    time: dt.datetime

    @property
    def date(self) -> dt.date:
        """Day of the rate."""
        return self.time.date()


@dataclass(frozen=True, slots=True)
class RatePoint:
    """A daily exchange rate.

    Attributes:
        date: Day of the rate.
        rate: Units of the base currency for one unit of the currency.
    """

    date: dt.date
    rate: Decimal


class ExchangeRateProvider(abc.ABC):
    """A source of exchange rates.

    Implementations provide [`latest`][picciuli.rates.ExchangeRateProvider.latest]
    and [`history`][picciuli.rates.ExchangeRateProvider.history], and raise
    [`PriceProviderError`][picciuli.errors.PriceProviderError] when they cannot
    answer. They must not touch the network until a method is called, must be
    constructible without arguments and safe to call from a worker thread.

    The class attributes `id`, `name` and `description` identify the provider
    in the [registry][picciuli.rates.register_rate_provider] and in user
    interfaces.
    """

    id: str
    """Stable identifier stored in the book settings, for example `"yahoo"`."""
    name: str
    """Human-readable name."""
    description: str = ""
    """One-line description for user interfaces."""

    @abc.abstractmethod
    def latest(self, currency: str, base: str) -> RateQuote:
        """Return the latest value of one unit of `currency` in `base`.

        Raises:
            PriceProviderError: If no rate is available.
        """

    @abc.abstractmethod
    def history(
        self, currency: str, base: str, start: dt.date, end: dt.date
    ) -> list[RatePoint]:
        """Return daily rates from `start` to `end` (inclusive).

        Raises:
            PriceProviderError: If the history is not available.
        """


class CachingRateProvider(ExchangeRateProvider):
    """Wrap a rate provider and reuse its latest rates for a while.

    At most `max_size` currency pairs are kept; the least recently used are
    dropped.

    Args:
        provider: The provider to wrap.
        ttl: How long a rate stays fresh, in seconds.
        clock: Monotonic clock (injectable for tests).
        max_size: Largest number of cached rates.
    """

    def __init__(
        self,
        provider: ExchangeRateProvider,
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
        self._rates: OrderedDict[tuple[str, str], tuple[float, RateQuote]] = (
            OrderedDict()
        )

    def latest(self, currency: str, base: str) -> RateQuote:
        """Return a cached rate if still fresh, otherwise ask the provider."""
        now = self._clock()
        key = (currency, base)
        with self._lock:
            cached = self._rates.get(key)
            if cached is not None and now - cached[0] < self.ttl:
                self._rates.move_to_end(key)
                return cached[1]
        quote = self.provider.latest(currency, base)
        with self._lock:
            self._rates[key] = (now, quote)
            self._rates.move_to_end(key)
            while len(self._rates) > self.max_size:
                self._rates.popitem(last=False)
        return quote

    def history(
        self, currency: str, base: str, start: dt.date, end: dt.date
    ) -> list[RatePoint]:
        """Delegate to the wrapped provider (not cached)."""
        return self.provider.history(currency, base, start, end)
