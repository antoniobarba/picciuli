"""Registry of price providers, including third-party plug-ins."""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from importlib.metadata import entry_points

from picciuli.errors import PriceProviderError, ValidationError

from .base import PriceProvider

__all__ = [
    "ENTRY_POINT_GROUP",
    "ProviderInfo",
    "available_providers",
    "create_provider",
    "provider_ids",
    "register_provider",
    "unregister_provider",
]

ENTRY_POINT_GROUP = "picciuli.price_providers"
"""Entry-point group scanned for third-party providers.

A plug-in package declares, in its `pyproject.toml`:

```toml
[project.entry-points."picciuli.price_providers"]
myquotes = "my_package.provider:MyQuotesProvider"
```
"""


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Description of a registered provider, for user interfaces.

    Attributes:
        id: Identifier stored in the book settings.
        name: Human-readable name.
        description: One-line description.
    """

    id: str
    name: str
    description: str


_providers: dict[str, type[PriceProvider]] = {}
_loaded = False


def _builtin_providers() -> builtins.list[type[PriceProvider]]:
    from .yahoo import YahooFinanceProvider

    return [YahooFinanceProvider]


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for provider in _builtin_providers():
        _providers.setdefault(provider.id, provider)
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            loaded = entry.load()
        except Exception:  # a broken plug-in must not break the book
            continue
        if isinstance(loaded, type) and issubclass(loaded, PriceProvider):
            _providers.setdefault(loaded.id, loaded)


def register_provider(
    provider: type[PriceProvider], *, replace: bool = False
) -> type[PriceProvider]:
    """Register a provider class under its `id`.

    Usable as a class decorator. Installed plug-ins are registered
    automatically through the entry-point group
    [`ENTRY_POINT_GROUP`][picciuli.prices.ENTRY_POINT_GROUP].

    Args:
        provider: A concrete [`PriceProvider`][picciuli.prices.PriceProvider]
            subclass with `id` and `name` class attributes.
        replace: Whether to replace a provider registered with the same `id`.

    Returns:
        The provider class, unchanged.

    Raises:
        ValidationError: If the class is not a provider, lacks an `id` or a
            `name`, or the `id` is taken and `replace` is false.
    """
    if not isinstance(provider, type) or not issubclass(provider, PriceProvider):
        raise ValidationError("a price provider must subclass PriceProvider")
    provider_id = getattr(provider, "id", None)
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ValidationError("a price provider needs a non-empty string id")
    if not isinstance(getattr(provider, "name", None), str):
        raise ValidationError("a price provider needs a string name")
    _ensure_loaded()
    if provider_id in _providers and not replace:
        raise ValidationError(f"price provider {provider_id!r} is already registered")
    _providers[provider_id] = provider
    return provider


def unregister_provider(provider_id: str) -> None:
    """Remove a provider from the registry; unknown identifiers are ignored."""
    _ensure_loaded()
    _providers.pop(provider_id, None)


def provider_ids() -> builtins.set[str]:
    """Return the identifiers of every registered provider."""
    _ensure_loaded()
    return set(_providers)


def available_providers() -> builtins.list[ProviderInfo]:
    """Return every registered provider, sorted by name."""
    _ensure_loaded()
    infos = [ProviderInfo(p.id, p.name, p.description) for p in _providers.values()]
    return sorted(infos, key=lambda info: (info.name.casefold(), info.id))


def create_provider(provider_id: str) -> PriceProvider:
    """Instantiate a registered provider with its default configuration.

    Raises:
        PriceProviderError: If no provider has this identifier.
    """
    _ensure_loaded()
    provider = _providers.get(provider_id)
    if provider is None:
        raise PriceProviderError(f"unknown price provider {provider_id!r}")
    return provider()
