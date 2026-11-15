from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from decimal import Decimal

import pytest

from picciuli import Book, ValidationError
from picciuli.errors import PriceProviderError
from picciuli.prices import ProviderInfo
from picciuli.rates import (
    CachingRateProvider,
    ExchangeRateProvider,
    RatePoint,
    RateQuote,
    YahooExchangeRateProvider,
    available_rate_providers,
    create_rate_provider,
    rate_provider_ids,
    register_rate_provider,
    registry,
    unregister_rate_provider,
)

NOON = dt.datetime(2025, 1, 2, 12, tzinfo=dt.timezone.utc)


class Fixed(ExchangeRateProvider):
    id = "fixed"
    name = "A fixed rate"
    description = "Always 2"

    def latest(self, currency: str, base: str) -> RateQuote:
        return RateQuote(currency, base, Decimal(2), NOON)

    def history(
        self, currency: str, base: str, start: dt.date, end: dt.date
    ) -> list[RatePoint]:
        return [RatePoint(start, Decimal(2))]


@pytest.fixture
def fixed() -> Iterator[type[Fixed]]:
    register_rate_provider(Fixed)
    yield Fixed
    unregister_rate_provider(Fixed.id)


class TestRegistry:
    def test_builtin_and_registered(self, fixed: type[Fixed]) -> None:
        assert {"yahoo", "fixed"} <= rate_provider_ids()
        assert available_rate_providers()[0] == ProviderInfo(
            "fixed", "A fixed rate", "Always 2"
        )
        assert isinstance(create_rate_provider("yahoo"), YahooExchangeRateProvider)
        quote = create_rate_provider("fixed").latest("USD", "EUR")
        assert (quote.rate, quote.date) == (Decimal(2), dt.date(2025, 1, 2))
        with pytest.raises(ValidationError, match="already"):
            register_rate_provider(Fixed)
        assert register_rate_provider(Fixed, replace=True) is Fixed

    def test_invalid_registrations(self) -> None:
        class NoId(Fixed):
            id = ""

        class NoName(Fixed):
            id = "noname"
            name = 3  # type: ignore[assignment]

        for bad in (str, NoId, NoName):
            with pytest.raises(ValidationError):
                register_rate_provider(bad)  # type: ignore[arg-type]
        with pytest.raises(PriceProviderError, match="unknown"):
            create_rate_provider("missing")
        unregister_rate_provider("missing")

    def test_entry_point_plugins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Entry:
            def __init__(self, value: object) -> None:
                self.value = value

            def load(self) -> object:
                if isinstance(self.value, Exception):
                    raise self.value
                return self.value

        entries = [Entry(Fixed), Entry(ImportError("broken")), Entry(int)]
        monkeypatch.setattr(registry, "_providers", {})
        monkeypatch.setattr(registry, "_loaded", False)
        monkeypatch.setattr(registry, "entry_points", lambda group: entries)
        assert rate_provider_ids() == {"yahoo", "fixed"}


def test_caching_rate_provider() -> None:
    calls: list[str] = []

    class Counting(Fixed):
        def latest(self, currency: str, base: str) -> RateQuote:
            calls.append(currency)
            return super().latest(currency, base)

    now = [0.0]
    cached = CachingRateProvider(Counting(), ttl=5, clock=lambda: now[0])
    assert (cached.id, cached.name, cached.description) == (
        "fixed",
        "A fixed rate",
        "Always 2",
    )
    cached.latest("USD", "EUR")
    cached.latest("USD", "EUR")
    cached.latest("GBP", "EUR")
    assert calls == ["USD", "GBP"]
    now[0] = 5
    cached.latest("USD", "EUR")
    assert calls == ["USD", "GBP", "USD"]
    day = dt.date(2025, 1, 1)
    assert cached.history("USD", "EUR", day, day) == [RatePoint(day, Decimal(2))]


class TestYahooRates:
    def test_latest_and_history(self) -> None:
        urls: list[str] = []
        bodies = [
            {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "currency": "EUR",
                                "regularMarketPrice": 0.9068,
                                "regularMarketTime": 1735819200,
                            }
                        }
                    ]
                }
            },
            {
                "chart": {
                    "result": [
                        {
                            "meta": {"currency": "EUR"},
                            "timestamp": [1735819200],
                            "indicators": {"quote": [{"close": [0.9123]}]},
                        }
                    ]
                }
            },
        ]

        def fetch(url: str) -> bytes:
            urls.append(url)
            return json.dumps(bodies.pop(0)).encode()

        provider = YahooExchangeRateProvider(fetch=fetch)
        quote = provider.latest(" usd ", "eur")
        assert (quote.currency, quote.base, quote.rate) == (
            "USD",
            "EUR",
            Decimal("0.9068"),
        )
        assert "USDEUR%3DX" in urls[0]
        day = dt.date(2025, 1, 2)
        assert provider.history("USD", "EUR", day, day) == [
            RatePoint(day, Decimal("0.9123"))
        ]
        with pytest.raises(PriceProviderError, match="three letters"):
            provider.latest("US", "EUR")


def test_rate_provider_setting(book: Book, fixed: type[Fixed]) -> None:
    assert book.settings.get().rate_provider == "yahoo"
    assert book.settings.update(rate_provider="fixed").rate_provider == "fixed"
    with pytest.raises(ValidationError, match="exchange-rate provider"):
        book.settings.update(rate_provider="nowhere")
