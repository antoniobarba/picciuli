from __future__ import annotations

from decimal import Decimal

import pytest

from api_tests.helpers import FakeClock, FakePrices, FakeRates, d
from picciuli import PriceProviderError
from picciuli_api.providers import SharedProviders


@pytest.fixture
def shared(
    fake_prices: FakePrices, fake_rates: FakeRates, clock: FakeClock
) -> SharedProviders:
    def prices(provider_id: str) -> FakePrices:
        if provider_id != "yahoo":
            raise PriceProviderError("unknown provider")
        return fake_prices

    return SharedProviders(
        ttl=900, clock=clock, price_factory=prices, rate_factory=lambda _: fake_rates
    )


def test_one_provider_per_id(shared: SharedProviders) -> None:
    assert shared.prices("yahoo") is shared.prices("yahoo")
    assert shared.rates("yahoo") is shared.rates("yahoo")


def test_quotes_are_reused_for_the_cache_period(
    shared: SharedProviders, fake_prices: FakePrices, clock: FakeClock
) -> None:
    fake_prices.add("AAPL", "200", "USD", d(10))
    for _ in range(3):
        assert shared.prices("yahoo").latest("AAPL").price == 200
    assert fake_prices.calls == ["AAPL"]
    clock.now += 899
    shared.prices("yahoo").latest("AAPL")
    assert fake_prices.calls == ["AAPL"]
    clock.now += 1
    shared.prices("yahoo").latest("AAPL")
    assert fake_prices.calls == ["AAPL", "AAPL"]


def test_rates_are_reused_for_the_cache_period(
    shared: SharedProviders, fake_rates: FakeRates, clock: FakeClock
) -> None:
    fake_rates.rates[("USD", "EUR")] = Decimal(1)
    shared.rates("yahoo").latest("USD", "EUR")
    shared.rates("yahoo").latest("USD", "EUR")
    assert fake_rates.calls == [("USD", "EUR")]
    clock.now += 900
    shared.rates("yahoo").latest("USD", "EUR")
    assert len(fake_rates.calls) == 2


def test_unknown_provider(shared: SharedProviders) -> None:
    with pytest.raises(PriceProviderError):
        shared.prices("nope")


def test_default_factories_use_the_registry() -> None:
    shared = SharedProviders(ttl=60)
    assert shared.prices("yahoo").id == "yahoo"
    assert shared.rates("yahoo").id == "yahoo"
    with pytest.raises(PriceProviderError):
        shared.prices("not-registered")
