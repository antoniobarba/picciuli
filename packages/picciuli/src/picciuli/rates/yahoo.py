"""Exchange rates from Yahoo Finance currency pairs."""

from __future__ import annotations

import datetime as dt

from picciuli.errors import PriceProviderError
from picciuli.prices import Fetch, YahooFinanceProvider

from .base import ExchangeRateProvider, RatePoint, RateQuote

__all__ = ["YahooExchangeRateProvider"]


def _codes(currency: str, base: str) -> tuple[str, str]:
    code, target = currency.strip().upper(), base.strip().upper()
    if len(code) != 3 or len(target) != 3:
        raise PriceProviderError("currency codes must have three letters")
    return code, target


class YahooExchangeRateProvider(ExchangeRateProvider):
    """Exchange rates from Yahoo Finance (pairs such as `USDEUR=X`).

    Free, no API key; rates are updated during the trading day. The endpoints
    are unofficial and may change or be rate limited.

    Args:
        fetch: Function downloading a URL (injectable for tests and proxies).
        timeout: Timeout of the default fetch, in seconds.
    """

    id = "yahoo"
    name = "Yahoo Finance"
    description = "Free intraday exchange rates for all major currencies (no API key)"

    def __init__(self, *, fetch: Fetch | None = None, timeout: float = 10.0) -> None:
        self._quotes = YahooFinanceProvider(fetch=fetch, timeout=timeout)

    def latest(self, currency: str, base: str) -> RateQuote:
        """Return the latest rate of the Yahoo currency pair."""
        code, target = _codes(currency, base)
        symbol = f"{code}{target}=X"
        quote = self._quotes.latest(symbol)
        return RateQuote(code, target, quote.price, quote.time)

    def history(
        self, currency: str, base: str, start: dt.date, end: dt.date
    ) -> list[RatePoint]:
        """Return the daily closing rates of the Yahoo currency pair."""
        code, target = _codes(currency, base)
        symbol = f"{code}{target}=X"
        return [
            RatePoint(p.date, p.price) for p in self._quotes.history(symbol, start, end)
        ]
