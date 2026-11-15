"""Exchange-rate providers: where currency conversion rates come from.

They convert the prices of securities quoted in a foreign currency into the
book currency. Like [price providers][picciuli.prices], they are modular: each
one is an [`ExchangeRateProvider`][picciuli.rates.ExchangeRateProvider]
subclass registered under a stable identifier, either with
[`register_rate_provider`][picciuli.rates.register_rate_provider] or as a
plug-in through the
[`RATE_ENTRY_POINT_GROUP`][picciuli.rates.RATE_ENTRY_POINT_GROUP] entry points.
The book settings select the one to use.

Example:
    ```python
    from picciuli.rates import available_rate_providers, create_rate_provider

    for info in available_rate_providers():
        print(info.id, info.name)
    print(create_rate_provider("yahoo").latest("USD", "EUR").rate)
    ```
"""

from .base import CachingRateProvider, ExchangeRateProvider, RatePoint, RateQuote
from .registry import (
    RATE_ENTRY_POINT_GROUP,
    available_rate_providers,
    create_rate_provider,
    rate_provider_ids,
    register_rate_provider,
    unregister_rate_provider,
)
from .yahoo import YahooExchangeRateProvider

__all__ = [
    "RATE_ENTRY_POINT_GROUP",
    "CachingRateProvider",
    "ExchangeRateProvider",
    "RatePoint",
    "RateQuote",
    "YahooExchangeRateProvider",
    "available_rate_providers",
    "create_rate_provider",
    "rate_provider_ids",
    "register_rate_provider",
    "unregister_rate_provider",
]
