"""Prices from Yahoo Finance (unofficial public endpoints, no API key)."""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from picciuli._decimal import rounded
from picciuli.errors import PriceProviderError

from .base import PricePoint, PriceProvider, Quote, SecurityInfo

__all__ = ["Fetch", "YahooFinanceProvider"]

Fetch = Callable[[str], bytes]
"""Function downloading a URL and returning the response body."""

_CHART_URL: Final = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_SEARCH_URL: Final = "https://query1.finance.yahoo.com/v1/finance/search"
_USER_AGENT: Final = "Mozilla/5.0 (compatible; picciuli)"

# Some exchanges quote in a subunit of the currency (London quotes in pence).
_SUBUNITS: Final[Mapping[str, tuple[str, int]]] = {
    "GBp": ("GBP", 100),
    "GBX": ("GBP", 100),
    "ZAc": ("ZAR", 100),
    "ZAC": ("ZAR", 100),
    "ILA": ("ILS", 100),
}


def _default_fetch(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body: bytes = response.read()
            return body
    except urllib.error.HTTPError as exc:
        # Unknown symbols come back as 404 with a JSON error description.
        if exc.code == 404:
            body = exc.read()
            return body
        raise PriceProviderError(f"Yahoo Finance answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise PriceProviderError(f"cannot reach Yahoo Finance: {exc}") from exc


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except InvalidOperation:  # pragma: no cover - repr of a float is valid
        return None
    if not result.is_finite() or result <= 0:
        return None
    return rounded(result)


def _currency(raw: object, price: Decimal) -> tuple[str | None, Decimal]:
    if not isinstance(raw, str) or not raw:
        return None, price
    if raw in _SUBUNITS:
        code, factor = _SUBUNITS[raw]
        return code, rounded(price / factor)
    return raw.upper(), price


class YahooFinanceProvider(PriceProvider):
    """Stocks, ETFs, funds and exchange rates from Yahoo Finance.

    No API key is needed. Symbols follow Yahoo conventions: a suffix selects
    the exchange, for example `AAPL` (Nasdaq), `VWCE.DE` (XETRA), `SWDA.MI`
    (Borsa Italiana), `VUSA.L` (London), `IWDA.AS` (Euronext Amsterdam).
    [`search`][picciuli.prices.YahooFinanceProvider.search] accepts an ISIN
    and lists the listings Yahoo knows.

    Yahoo has no gettex listing. Prices on gettex follow the main exchanges
    closely, so value a security bought on gettex with another listing of the
    same ISIN, typically XETRA (`.DE`).

    Prices quoted in pence (London) are converted to pounds.

    The endpoints are unofficial and may change or be rate limited; failures
    raise [`PriceProviderError`][picciuli.errors.PriceProviderError].

    Args:
        fetch: Function downloading a URL (injectable for tests and proxies).
            Defaults to `urllib` with a 10 second timeout.
        timeout: Timeout of the default fetch, in seconds.
    """

    id = "yahoo"
    name = "Yahoo Finance"
    description = (
        "Free delayed quotes for stocks, ETFs and currencies on US and European "
        "exchanges (no API key)"
    )

    def __init__(self, *, fetch: Fetch | None = None, timeout: float = 10.0) -> None:
        self._fetch: Fetch = fetch or (lambda url: _default_fetch(url, timeout))

    def _json(self, url: str) -> Any:
        body = self._fetch(url)
        try:
            return json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PriceProviderError("Yahoo Finance sent an invalid response") from exc

    def _chart(self, symbol: str, query: Mapping[str, str]) -> dict[str, Any]:
        if not isinstance(symbol, str) or not symbol.strip():
            raise PriceProviderError("the symbol cannot be empty")
        url = (
            _CHART_URL.format(symbol=urllib.parse.quote(symbol.strip(), safe=""))
            + "?"
            + urllib.parse.urlencode(query)
        )
        data = self._json(url)
        chart = data.get("chart") if isinstance(data, dict) else None
        if not isinstance(chart, dict):
            raise PriceProviderError("Yahoo Finance sent an unexpected response")
        error = chart.get("error")
        if error:
            detail = error.get("description") if isinstance(error, dict) else error
            raise PriceProviderError(f"Yahoo Finance: {symbol}: {detail}")
        results = chart.get("result")
        if not isinstance(results, list) or not results:
            raise PriceProviderError(f"Yahoo Finance has no data for {symbol}")
        result = results[0]
        if not isinstance(result, dict) or not isinstance(result.get("meta"), dict):
            raise PriceProviderError("Yahoo Finance sent an unexpected response")
        return result

    @staticmethod
    def _zone(meta: Mapping[str, Any]) -> dt.timezone:
        offset = meta.get("gmtoffset")
        if isinstance(offset, int) and not isinstance(offset, bool):
            return dt.timezone(dt.timedelta(seconds=offset))
        return dt.timezone.utc

    def latest(self, symbol: str) -> Quote:
        """Return the regular-market price (usually delayed by 15 minutes)."""
        result = self._chart(symbol, {"range": "1d", "interval": "1d"})
        meta: dict[str, Any] = result["meta"]
        price = _decimal(meta.get("regularMarketPrice"))
        if price is None:
            raise PriceProviderError(f"Yahoo Finance has no price for {symbol}")
        currency, price = _currency(meta.get("currency"), price)
        stamp = meta.get("regularMarketTime")
        zone = self._zone(meta)
        if isinstance(stamp, int) and not isinstance(stamp, bool):
            moment = dt.datetime.fromtimestamp(stamp, zone)
        else:
            moment = dt.datetime.now(zone)
        name = meta.get("longName") or meta.get("shortName")
        return Quote(
            symbol=str(meta.get("symbol") or symbol),
            price=price,
            currency=currency,
            time=moment,
            name=name if isinstance(name, str) else None,
        )

    def history(self, symbol: str, start: dt.date, end: dt.date) -> list[PricePoint]:
        """Return daily closing prices (not adjusted for dividends)."""
        if start > end:
            raise PriceProviderError("start must be on or before end")
        first = dt.datetime.combine(start, dt.time(), dt.timezone.utc)
        last = dt.datetime.combine(
            end + dt.timedelta(days=1), dt.time(), dt.timezone.utc
        )
        result = self._chart(
            symbol,
            {
                "period1": str(int(first.timestamp())),
                "period2": str(int(last.timestamp())),
                "interval": "1d",
            },
        )
        meta: dict[str, Any] = result["meta"]
        zone = self._zone(meta)
        stamps = result.get("timestamp") or []
        indicators = result.get("indicators")
        closes: list[Any] = []
        if isinstance(indicators, dict):
            quotes = indicators.get("quote")
            if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict):
                closes = quotes[0].get("close") or []
        points: dict[dt.date, Decimal] = {}
        for stamp, close in zip(stamps, closes, strict=False):
            price = _decimal(close)
            if price is None or not isinstance(stamp, int):
                continue
            # Historical closes are single-precision floats: keep 7 significant
            # digits so that 169.38000488 becomes 169.38.
            price = rounded(Decimal(format(price, ".7g")))
            _, price = _currency(meta.get("currency"), price)
            day = dt.datetime.fromtimestamp(stamp, zone).date()
            if start <= day <= end:
                points[day] = price
        return [PricePoint(day, points[day]) for day in sorted(points)]

    def exchange_rate_symbol(self, currency: str, base: str) -> str | None:
        """Return the Yahoo currency pair, for example `USDEUR=X`."""
        return f"{currency.upper()}{base.upper()}=X"

    def search(self, query: str) -> list[SecurityInfo]:
        """Search by name, symbol or ISIN."""
        text = query.strip() if isinstance(query, str) else ""
        if not text:
            return []
        url = (
            _SEARCH_URL
            + "?"
            + urllib.parse.urlencode(
                {"q": text, "quotesCount": "20", "newsCount": "0", "listsCount": "0"}
            )
        )
        data = self._json(url)
        quotes = data.get("quotes") if isinstance(data, dict) else None
        if not isinstance(quotes, list):
            raise PriceProviderError("Yahoo Finance sent an unexpected response")
        found: list[SecurityInfo] = []
        for item in quotes:
            if not isinstance(item, dict) or not isinstance(item.get("symbol"), str):
                continue
            name = item.get("longname") or item.get("shortname") or item["symbol"]
            exchange = item.get("exchDisp") or item.get("exchange")
            kind = item.get("typeDisp") or item.get("quoteType")
            found.append(
                SecurityInfo(
                    symbol=item["symbol"],
                    name=str(name),
                    exchange=str(exchange) if exchange else None,
                    kind=str(kind) if kind else None,
                )
            )
        return found
