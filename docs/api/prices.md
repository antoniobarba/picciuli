# Price providers

A price provider downloads security prices; exchange rates come from an
[exchange-rate provider](rates.md). The library
never touches the network by itself: prices are only fetched when you call
[`InvestmentService.refresh_prices`][picciuli.services.InvestmentService.refresh_prices]
or use a provider directly.

```python
import datetime as dt

from picciuli import Book
from picciuli.prices import available_providers, create_provider

for info in available_providers():
    print(info.id, info.name, "-", info.description)

with Book.open("finance.db") as book:
    # Uses the provider selected in the settings ("yahoo" by default).
    update = book.investments.refresh_prices(history_start=dt.date(2025, 1, 1))
    for message in update.errors:
        print("not updated:", message)

provider = create_provider("yahoo")
print(provider.search("IE00BK5BQT80"))  # listings of an ISIN
print(provider.latest("VWCE.DE").price)  # latest quote
```

For a display that follows the market, call `refresh_prices` periodically, for
example every minute from a worker thread. Each call replaces the price of the
current trading day, so the book keeps one price per security and day.
[`CachingProvider`][picciuli.prices.CachingProvider] avoids asking the source
again for quotes that are still fresh.

## Writing a provider

A provider is a subclass of [`PriceProvider`][picciuli.prices.PriceProvider]
with an `id`, a `name` and two methods. It must be constructible without
arguments and raise [`PriceProviderError`][picciuli.errors.PriceProviderError]
when it cannot answer.

```python
import datetime as dt
from decimal import Decimal

from picciuli.errors import PriceProviderError
from picciuli.prices import PricePoint, PriceProvider, Quote, register_provider


@register_provider
class MyQuotes(PriceProvider):
    id = "myquotes"
    name = "My quotes"
    description = "Prices from my own service"

    def latest(self, symbol: str) -> Quote:
        price = ...  # ask your service
        if price is None:
            raise PriceProviderError(f"no price for {symbol}")
        return Quote(symbol, Decimal(price), "EUR", dt.datetime.now(dt.timezone.utc))

    def history(self, symbol: str, start: dt.date, end: dt.date) -> list[PricePoint]:
        return []

    # Optional: the symbol of a currency pair, and search.
    def exchange_rate_symbol(self, currency: str, base: str) -> str | None:
        return f"{currency}{base}"
```

`exchange_rate_symbol` is informational: exchange rates are downloaded by
[exchange-rate providers](rates.md).

Once registered, the provider appears in
[`available_providers`][picciuli.prices.available_providers] and can be
selected with `book.settings.update(price_provider="myquotes")`.

To ship a provider as a separate package, declare it as an entry point. The
library discovers it automatically, without any import in your code:

```toml
[project.entry-points."picciuli.price_providers"]
myquotes = "my_package.provider:MyQuotes"
```

## Reference

::: picciuli.prices.PriceProvider

::: picciuli.prices.Quote

::: picciuli.prices.PricePoint

::: picciuli.prices.SecurityInfo

::: picciuli.prices.CachingProvider

::: picciuli.prices.YahooFinanceProvider

::: picciuli.prices.ProviderInfo

::: picciuli.prices.available_providers

::: picciuli.prices.create_provider

::: picciuli.prices.provider_ids

::: picciuli.prices.register_provider

::: picciuli.prices.unregister_provider

::: picciuli.prices.ENTRY_POINT_GROUP
