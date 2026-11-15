from __future__ import annotations

import datetime as dt
import io
import json
import urllib.error
from collections.abc import Iterator
from decimal import Decimal
from email.message import Message
from typing import Any

import pytest

from picciuli import ValidationError
from picciuli.errors import PriceProviderError
from picciuli.prices import (
    CachingProvider,
    PricePoint,
    PriceProvider,
    ProviderInfo,
    Quote,
    SecurityInfo,
    YahooFinanceProvider,
    available_providers,
    create_provider,
    provider_ids,
    register_provider,
    registry,
    unregister_provider,
    yahoo,
)


class Static(PriceProvider):
    id = "static"
    name = "Static prices"
    description = "Always 1"

    def latest(self, symbol: str) -> Quote:
        return Quote(symbol, Decimal(1), "EUR", dt.datetime(2025, 1, 1, 12))

    def history(self, symbol: str, start: dt.date, end: dt.date) -> list[PricePoint]:
        return []


@pytest.fixture
def static() -> Iterator[type[Static]]:
    register_provider(Static)
    yield Static
    unregister_provider(Static.id)


class TestRegistry:
    def test_builtin_and_registered_providers(self, static: type[Static]) -> None:
        assert {"yahoo", "static"} <= provider_ids()
        assert available_providers()[0] == ProviderInfo(
            "static", "Static prices", "Always 1"
        )
        assert isinstance(create_provider("yahoo"), YahooFinanceProvider)
        provider = create_provider("static")
        assert provider.latest("X").price == 1
        assert provider.search("x") == []
        assert provider.exchange_rate_symbol("USD", "EUR") is None
        with pytest.raises(ValidationError, match="already"):
            register_provider(Static)
        assert register_provider(Static, replace=True) is Static

    def test_invalid_registrations(self) -> None:
        class NoId(Static):
            id = " "

        class NoName(Static):
            id = "noname"
            name = None  # type: ignore[assignment]

        for bad in (int, NoId, NoName):
            with pytest.raises(ValidationError):
                register_provider(bad)  # type: ignore[arg-type]
        with pytest.raises(PriceProviderError, match="unknown"):
            create_provider("missing")
        unregister_provider("missing")

    def test_entry_point_plugins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Entry:
            def __init__(self, value: object) -> None:
                self.value = value

            def load(self) -> object:
                if isinstance(self.value, Exception):
                    raise self.value
                return self.value

        entries = [Entry(Static), Entry(ImportError("broken")), Entry(object)]
        monkeypatch.setattr(registry, "_providers", {})
        monkeypatch.setattr(registry, "_loaded", False)
        monkeypatch.setattr(registry, "entry_points", lambda group: entries)
        assert provider_ids() == {"yahoo", "static"}


class TestCachingProvider:
    def test_quotes_are_reused_until_they_expire(self) -> None:
        calls: list[str] = []

        class Counting(Static):
            def latest(self, symbol: str) -> Quote:
                calls.append(symbol)
                return super().latest(symbol)

        now = [0.0]
        cached = CachingProvider(Counting(), ttl=10, clock=lambda: now[0])
        assert (cached.id, cached.name, cached.description) == (
            "static",
            "Static prices",
            "Always 1",
        )
        cached.latest("A")
        now[0] = 9
        cached.latest("A")
        assert calls == ["A"]
        now[0] = 10
        cached.latest("A")
        assert calls == ["A", "A"]
        assert cached.history("A", dt.date(2025, 1, 1), dt.date(2025, 1, 2)) == []
        assert cached.exchange_rate_symbol("USD", "EUR") is None
        assert cached.search("A") == []

    def test_cache_keeps_the_most_recently_used_symbols(self) -> None:
        calls: list[str] = []

        class Counting(Static):
            def latest(self, symbol: str) -> Quote:
                calls.append(symbol)
                return super().latest(symbol)

        cached = CachingProvider(Counting(), ttl=60, clock=lambda: 0.0, max_size=2)
        for symbol in ("A", "B", "A", "C", "A", "B"):
            cached.latest(symbol)
        # C evicted B (the least recently used); B then evicted C.
        assert calls == ["A", "B", "C", "B"]
        assert len(cached._quotes) == 2


def chart(meta: dict[str, Any], **extra: Any) -> bytes:
    return json.dumps(
        {"chart": {"result": [{"meta": meta, **extra}], "error": None}}
    ).encode()


class FakeFetch:
    def __init__(self, *bodies: bytes) -> None:
        self.bodies = list(bodies)
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.bodies.pop(0)


CET = dt.timezone(dt.timedelta(hours=1))


class TestYahoo:
    def test_latest(self) -> None:
        fetch = FakeFetch(
            chart(
                {
                    "symbol": "VWCE.DE",
                    "currency": "EUR",
                    "regularMarketPrice": 169.86,
                    "regularMarketTime": 1763051764,
                    "gmtoffset": 3600,
                    "longName": "Vanguard FTSE All-World",
                }
            )
        )
        quote = YahooFinanceProvider(fetch=fetch).latest(" VWCE.DE ")
        assert quote == Quote(
            "VWCE.DE",
            Decimal("169.86"),
            "EUR",
            dt.datetime(2025, 11, 13, 17, 36, 4, tzinfo=CET),
            "Vanguard FTSE All-World",
        )
        assert quote.date == dt.date(2025, 11, 13)
        assert fetch.urls == [
            "https://query1.finance.yahoo.com/v8/finance/chart/VWCE.DE"
            "?range=1d&interval=1d"
        ]

    def test_latest_in_pence_without_time(self) -> None:
        fetch = FakeFetch(chart({"currency": "GBp", "regularMarketPrice": 10801}))
        quote = YahooFinanceProvider(fetch=fetch).latest("VUSA.L")
        assert (quote.symbol, quote.price, quote.currency, quote.name) == (
            "VUSA.L",
            Decimal("108.01"),
            "GBP",
            None,
        )
        assert quote.time.tzinfo == dt.timezone.utc

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            (b"not json", "invalid response"),
            (b"[]", "unexpected"),
            (
                json.dumps(
                    {"chart": {"result": None, "error": {"description": "Not found"}}}
                ).encode(),
                "Not found",
            ),
            (json.dumps({"chart": {"result": []}}).encode(), "no data"),
            (json.dumps({"chart": {"result": [1]}}).encode(), "unexpected"),
            (chart({"currency": "EUR"}), "no price"),
            (chart({"regularMarketPrice": True}), "no price"),
        ],
    )
    def test_latest_errors(self, body: bytes, message: str) -> None:
        with pytest.raises(PriceProviderError, match=message):
            YahooFinanceProvider(fetch=FakeFetch(body)).latest("X")

    def test_empty_symbol(self) -> None:
        with pytest.raises(PriceProviderError, match="empty"):
            YahooFinanceProvider(fetch=FakeFetch()).latest(" ")

    def test_history(self) -> None:
        day = 1762156800  # 2025-11-03 08:00 CET
        fetch = FakeFetch(
            chart(
                {"currency": "EUR", "gmtoffset": 3600},
                timestamp=[day, day + 86400, day + 2 * 86400, day + 9 * 86400, "x"],
                indicators={"quote": [{"close": [169.38000488, None, 165.9, 1.0, 2]}]},
            ),
            chart({"currency": "EUR"}),
        )
        provider = YahooFinanceProvider(fetch=fetch)
        points = provider.history("VWCE.DE", dt.date(2025, 11, 3), dt.date(2025, 11, 6))
        assert points == [
            PricePoint(dt.date(2025, 11, 3), Decimal("169.38")),
            PricePoint(dt.date(2025, 11, 5), Decimal("165.9")),
        ]
        assert "period1=1762128000&period2=1762473600" in fetch.urls[0]
        assert provider.history("X", dt.date(2025, 1, 1), dt.date(2025, 1, 1)) == []
        with pytest.raises(PriceProviderError, match="start"):
            provider.history("X", dt.date(2025, 1, 2), dt.date(2025, 1, 1))

    def test_exchange_rate_symbol(self) -> None:
        assert YahooFinanceProvider().exchange_rate_symbol("usd", "eur") == "USDEUR=X"

    def test_search(self) -> None:
        body = json.dumps(
            {
                "quotes": [
                    {
                        "symbol": "VWCE.DE",
                        "longname": "Vanguard FTSE All-World",
                        "exchDisp": "XETRA",
                        "typeDisp": "ETF",
                    },
                    {"symbol": "X.MI", "shortname": "X", "exchange": "MIL"},
                    {"symbol": "Y"},
                    {"name": "no symbol"},
                ]
            }
        ).encode()
        fetch = FakeFetch(body)
        provider = YahooFinanceProvider(fetch=fetch)
        assert provider.search(" IE00BK5BQT80 ") == [
            SecurityInfo("VWCE.DE", "Vanguard FTSE All-World", "XETRA", "ETF"),
            SecurityInfo("X.MI", "X", "MIL", None),
            SecurityInfo("Y", "Y", None, None),
        ]
        assert "q=IE00BK5BQT80" in fetch.urls[0]
        assert provider.search("  ") == []
        with pytest.raises(PriceProviderError, match="unexpected"):
            YahooFinanceProvider(fetch=FakeFetch(b"{}")).search("x")

    def test_default_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Response(io.BytesIO):
            def __enter__(self) -> Response:
                return self

        def ok(request: Any, timeout: float) -> Response:
            assert request.get_header("User-agent").startswith("Mozilla/5.0")
            assert timeout == 3
            return Response(b"body")

        monkeypatch.setattr("urllib.request.urlopen", ok)
        assert yahoo._default_fetch("https://example.test", 3) == b"body"

        def failing(error: Exception) -> Any:
            def urlopen(request: Any, timeout: float) -> Any:
                raise error

            return urlopen

        not_found = urllib.error.HTTPError(
            "u", 404, "Not Found", Message(), io.BytesIO(b"{}")
        )
        monkeypatch.setattr("urllib.request.urlopen", failing(not_found))
        assert yahoo._default_fetch("https://u.test", 1) == b"{}"
        too_many = urllib.error.HTTPError("u", 429, "Too Many", Message(), io.BytesIO())
        monkeypatch.setattr("urllib.request.urlopen", failing(too_many))
        with pytest.raises(PriceProviderError, match="429"):
            yahoo._default_fetch("https://u.test", 1)
        offline = urllib.error.URLError("offline")
        monkeypatch.setattr("urllib.request.urlopen", failing(offline))
        with pytest.raises(PriceProviderError, match="cannot reach"):
            yahoo._default_fetch("https://u.test", 1)
        not_found.close()
        too_many.close()
