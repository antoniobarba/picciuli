# Exchange-rate providers

An exchange-rate provider downloads the value of foreign currencies in the
book currency. It converts the prices of securities quoted in another currency
(for example Apple in USD in a EUR book). The book settings select the provider
(`rate_provider`, default `"yahoo"`), separately from the
[price provider](prices.md).

```python
from picciuli import Book
from picciuli.rates import available_rate_providers, create_rate_provider

for info in available_rate_providers():
    print(info.id, info.name, "-", info.description)

with Book.open("finance.db") as book:
    book.settings.update(currency_code="EUR", rate_provider="yahoo")
    # Rates are refreshed together with prices...
    book.investments.refresh_prices()
    # ...or on their own, for every currency of your securities.
    book.investments.refresh_exchange_rates()

print(create_rate_provider("yahoo").latest("USD", "EUR").rate)
```

Like prices, a rate is stored at most once per currency and day; refreshing
replaces the rate of the current day.
[`Holding.converted_price`][picciuli.model.Holding] and
[`SecurityService.latest_price_in_book_currency`][picciuli.services.SecurityService.latest_price_in_book_currency]
give prices in the book currency.

## Writing a provider

Subclass [`ExchangeRateProvider`][picciuli.rates.ExchangeRateProvider],
implement `latest` and `history`, and raise
[`PriceProviderError`][picciuli.errors.PriceProviderError] when no rate is
available:

```python
import datetime as dt
from decimal import Decimal

from picciuli.rates import (
    ExchangeRateProvider,
    RatePoint,
    RateQuote,
    register_rate_provider,
)


@register_rate_provider
class MyRates(ExchangeRateProvider):
    id = "myrates"
    name = "My rates"
    description = "Rates from my own service"

    def latest(self, currency: str, base: str) -> RateQuote:
        rate = Decimal("0.92")  # ask your service
        return RateQuote(currency, base, rate, dt.datetime.now(dt.timezone.utc))

    def history(
        self, currency: str, base: str, start: dt.date, end: dt.date
    ) -> list[RatePoint]:
        return []
```

Packages can also declare the provider as an entry point; it is discovered
automatically:

```toml
[project.entry-points."picciuli.rate_providers"]
myrates = "my_package.rates:MyRates"
```

## Reference

::: picciuli.rates.ExchangeRateProvider

::: picciuli.rates.RateQuote

::: picciuli.rates.RatePoint

::: picciuli.rates.CachingRateProvider

::: picciuli.rates.YahooExchangeRateProvider

::: picciuli.rates.available_rate_providers

::: picciuli.rates.create_rate_provider

::: picciuli.rates.rate_provider_ids

::: picciuli.rates.register_rate_provider

::: picciuli.rates.unregister_rate_provider

::: picciuli.rates.RATE_ENTRY_POINT_GROUP
