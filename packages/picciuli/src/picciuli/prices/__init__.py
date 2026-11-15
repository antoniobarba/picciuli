"""Price providers: where security prices and exchange rates come from.

The library never touches the network by itself. A
[`PriceProvider`][picciuli.prices.PriceProvider] fetches quotes when asked, and
[`InvestmentService.refresh_prices`][picciuli.services.InvestmentService.refresh_prices]
stores them in the book.

Providers are modular: each one is a `PriceProvider` subclass registered under
a stable identifier. The built-in
[`YahooFinanceProvider`][picciuli.prices.YahooFinanceProvider]
is always available; others can be added with
[`register_provider`][picciuli.prices.register_provider] or installed as
plug-ins through the [`ENTRY_POINT_GROUP`][picciuli.prices.ENTRY_POINT_GROUP]
entry points. The book settings select the provider to use.

Example:
    ```python
    from picciuli.prices import available_providers, create_provider

    for info in available_providers():
        print(info.id, info.name)
    provider = create_provider("yahoo")
    print(provider.latest("VWCE.DE").price)
    ```
"""

from picciuli.errors import PriceProviderError

from .base import CachingProvider, PricePoint, PriceProvider, Quote, SecurityInfo
from .registry import (
    ENTRY_POINT_GROUP,
    ProviderInfo,
    available_providers,
    create_provider,
    provider_ids,
    register_provider,
    unregister_provider,
)
from .yahoo import Fetch, YahooFinanceProvider

__all__ = [
    "ENTRY_POINT_GROUP",
    "CachingProvider",
    "Fetch",
    "PricePoint",
    "PriceProvider",
    "PriceProviderError",
    "ProviderInfo",
    "Quote",
    "SecurityInfo",
    "YahooFinanceProvider",
    "available_providers",
    "create_provider",
    "provider_ids",
    "register_provider",
    "unregister_provider",
]
