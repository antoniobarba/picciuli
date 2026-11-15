"""Registry of exchange-rate providers, including third-party plug-ins."""

from __future__ import annotations

import builtins
from importlib.metadata import entry_points

from picciuli.errors import PriceProviderError, ValidationError
from picciuli.prices import ProviderInfo

from .base import ExchangeRateProvider

__all__ = [
    "RATE_ENTRY_POINT_GROUP",
    "available_rate_providers",
    "create_rate_provider",
    "rate_provider_ids",
    "register_rate_provider",
    "unregister_rate_provider",
]

RATE_ENTRY_POINT_GROUP = "picciuli.rate_providers"
"""Entry-point group scanned for third-party exchange-rate providers.

A plug-in package declares, in its `pyproject.toml`:

```toml
[project.entry-points."picciuli.rate_providers"]
myrates = "my_package.rates:MyRatesProvider"
```
"""

_providers: dict[str, type[ExchangeRateProvider]] = {}
_loaded = False


def _builtin_providers() -> builtins.list[type[ExchangeRateProvider]]:
    from .yahoo import YahooExchangeRateProvider

    return [YahooExchangeRateProvider]


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for provider in _builtin_providers():
        _providers.setdefault(provider.id, provider)
    for entry in entry_points(group=RATE_ENTRY_POINT_GROUP):
        try:
            loaded = entry.load()
        except Exception:  # a broken plug-in must not break the book
            continue
        if isinstance(loaded, type) and issubclass(loaded, ExchangeRateProvider):
            _providers.setdefault(loaded.id, loaded)


def register_rate_provider(
    provider: type[ExchangeRateProvider], *, replace: bool = False
) -> type[ExchangeRateProvider]:
    """Register an exchange-rate provider class under its `id`.

    Usable as a class decorator.

    Args:
        provider: A concrete
            [`ExchangeRateProvider`][picciuli.rates.ExchangeRateProvider]
            subclass with `id` and `name` class attributes.
        replace: Whether to replace a provider registered with the same `id`.

    Returns:
        The provider class, unchanged.

    Raises:
        ValidationError: If the class is not a rate provider, lacks an `id` or
            a `name`, or the `id` is taken and `replace` is false.
    """
    if not isinstance(provider, type) or not issubclass(provider, ExchangeRateProvider):
        raise ValidationError(
            "an exchange-rate provider must subclass ExchangeRateProvider"
        )
    provider_id = getattr(provider, "id", None)
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ValidationError("an exchange-rate provider needs a non-empty string id")
    if not isinstance(getattr(provider, "name", None), str):
        raise ValidationError("an exchange-rate provider needs a string name")
    _ensure_loaded()
    if provider_id in _providers and not replace:
        raise ValidationError(
            f"exchange-rate provider {provider_id!r} is already registered"
        )
    _providers[provider_id] = provider
    return provider


def unregister_rate_provider(provider_id: str) -> None:
    """Remove a rate provider from the registry; unknown ids are ignored."""
    _ensure_loaded()
    _providers.pop(provider_id, None)


def rate_provider_ids() -> builtins.set[str]:
    """Return the identifiers of every registered rate provider."""
    _ensure_loaded()
    return set(_providers)


def available_rate_providers() -> builtins.list[ProviderInfo]:
    """Return every registered rate provider, sorted by name."""
    _ensure_loaded()
    infos = [ProviderInfo(p.id, p.name, p.description) for p in _providers.values()]
    return sorted(infos, key=lambda info: (info.name.casefold(), info.id))


def create_rate_provider(provider_id: str) -> ExchangeRateProvider:
    """Instantiate a registered rate provider with its default configuration.

    Raises:
        PriceProviderError: If no rate provider has this identifier.
    """
    _ensure_loaded()
    provider = _providers.get(provider_id)
    if provider is None:
        raise PriceProviderError(f"unknown exchange-rate provider {provider_id!r}")
    return provider()
