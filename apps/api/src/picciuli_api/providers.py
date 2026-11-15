"""Price and exchange-rate providers shared by every user.

Quotes are public data, so one cache serves all users: however many users
refresh their prices, each symbol is downloaded at most once per cache period
(15 minutes by default).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from picciuli.prices import CachingProvider, PriceProvider, create_provider
from picciuli.rates import (
    CachingRateProvider,
    ExchangeRateProvider,
    create_rate_provider,
)

__all__ = ["SharedProviders"]


class SharedProviders:
    """Process-wide caching wrappers around the registered providers.

    Args:
        ttl: How long a quote or a rate is reused, in seconds.
        clock: Monotonic clock (injectable for tests).
        price_factory: Creates a price provider from its identifier.
        rate_factory: Creates an exchange-rate provider from its identifier.
    """

    def __init__(
        self,
        *,
        ttl: float,
        clock: Callable[[], float] = time.monotonic,
        price_factory: Callable[[str], PriceProvider] = create_provider,
        rate_factory: Callable[[str], ExchangeRateProvider] = create_rate_provider,
    ) -> None:
        self.ttl = ttl
        self._clock = clock
        self._price_factory = price_factory
        self._rate_factory = rate_factory
        self._lock = threading.Lock()
        self._prices: dict[str, CachingProvider] = {}
        self._rates: dict[str, CachingRateProvider] = {}

    def prices(self, provider_id: str) -> PriceProvider:
        """Return the shared, caching price provider with this identifier.

        Raises:
            PriceProviderError: If no such provider is registered.
        """
        with self._lock:
            provider = self._prices.get(provider_id)
            if provider is None:
                provider = CachingProvider(
                    self._price_factory(provider_id), ttl=self.ttl, clock=self._clock
                )
                self._prices[provider_id] = provider
            return provider

    def rates(self, provider_id: str) -> ExchangeRateProvider:
        """Return the shared, caching exchange-rate provider with this identifier.

        Raises:
            PriceProviderError: If no such provider is registered.
        """
        with self._lock:
            provider = self._rates.get(provider_id)
            if provider is None:
                provider = CachingRateProvider(
                    self._rate_factory(provider_id), ttl=self.ttl, clock=self._clock
                )
                self._rates[provider_id] = provider
            return provider
