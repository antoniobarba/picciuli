"""Bodies of the security, price, exchange-rate and investment endpoints."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from picciuli import SecurityKind

from .accounts import AccountOut
from .base import (
    MAX_LIST_LENGTH,
    CurrencyCode,
    Date,
    DecimalStr,
    Id,
    InputModel,
    Name,
    NonNegativeAmount,
    OutputModel,
    PatchModel,
    PositiveAmount,
    PositiveDecimal,
    Symbol,
    Text,
)

__all__ = [
    "AccountValuationOut",
    "BuyCreate",
    "ExchangeRateIn",
    "ExchangeRateOut",
    "HoldingOut",
    "LatestExchangeRateOut",
    "LatestPriceOut",
    "PriceIn",
    "PriceOut",
    "PriceUpdateOut",
    "ProviderOut",
    "RefreshExchangeRates",
    "RefreshPrices",
    "SaleCostOut",
    "SecurityCreate",
    "SecurityInfoOut",
    "SecurityOut",
    "SecurityUpdate",
    "SellCreate",
]


class SecurityOut(OutputModel):
    """Something you can hold shares of."""

    id: int
    name: str
    symbol: str | None
    isin: str | None
    currency: str
    kind: SecurityKind
    notes: str | None


class SecurityCreate(InputModel):
    """A new security."""

    name: Name = Field(examples=["Vanguard FTSE All-World"])
    currency: CurrencyCode
    kind: SecurityKind = SecurityKind.STOCK
    symbol: Symbol | None = Field(default=None, examples=["VWCE.DE"])
    isin: Symbol | None = Field(default=None, examples=["IE00BK5BQT80"])
    notes: Text | None = None


class SecurityUpdate(PatchModel):
    """Changes to a security."""

    _not_null = frozenset({"name", "currency", "kind"})

    name: Name | None = None
    currency: CurrencyCode | None = None
    kind: SecurityKind | None = None
    symbol: Symbol | None = None
    isin: Symbol | None = None
    notes: Text | None = None


class PriceOut(OutputModel):
    """The price of one share on a day, in the security's currency."""

    security_id: int
    date: dt.date
    price: DecimalStr
    source: str | None


class PriceIn(InputModel):
    """A price entered by hand."""

    price: PositiveDecimal = Field(examples=["112.34"])
    source: Name | None = None


class LatestPriceOut(OutputModel):
    """The latest known price of a security."""

    price: PriceOut | None
    price_in_book_currency: DecimalStr | None


class ExchangeRateOut(OutputModel):
    """Book currency per one unit of a foreign currency."""

    currency: str
    date: dt.date
    rate: DecimalStr


class ExchangeRateIn(InputModel):
    """An exchange rate entered by hand."""

    rate: PositiveDecimal = Field(examples=["0.92"])


class LatestExchangeRateOut(OutputModel):
    """The latest known exchange rate of a currency."""

    exchange_rate: ExchangeRateOut | None


class HoldingOut(OutputModel):
    """Shares of one security held in an account."""

    security: SecurityOut
    quantity: DecimalStr
    cost_basis: int
    price: DecimalStr | None
    price_date: dt.date | None
    exchange_rate: DecimalStr | None
    market_value: int | None
    converted_price: DecimalStr | None
    unrealized_gain: int | None


class AccountValuationOut(OutputModel):
    """The market value of an account."""

    account: AccountOut
    as_of: dt.date | None
    balance: int
    holdings: list[HoldingOut]
    cost_basis: int
    cash: int
    market_value: int
    unrealized_gain: int
    is_complete: bool


class SaleCostOut(OutputModel):
    """Cost basis of shares that would be sold."""

    cost: int


class BuyCreate(InputModel):
    """A purchase of shares."""

    date: Date
    account_id: Id
    security_id: Id
    quantity: PositiveDecimal = Field(examples=["1.5"])
    cost: PositiveAmount = Field(
        description="Price paid for the shares, in minor units."
    )
    from_account_id: Id | None = None
    fee: NonNegativeAmount = 0
    fee_category_id: Id | None = None
    description: Text | None = None
    notes: Text | None = None


class SellCreate(InputModel):
    """A sale of shares."""

    date: Date
    account_id: Id
    security_id: Id
    quantity: PositiveDecimal = Field(examples=["1.5"])
    proceeds: PositiveAmount = Field(description="Gross sale proceeds, in minor units.")
    to_account_id: Id | None = None
    fee: NonNegativeAmount = 0
    fee_category_id: Id | None = None
    tax: NonNegativeAmount = 0
    tax_category_id: Id | None = None
    gain_category_id: Id | None = None
    description: Text | None = None
    notes: Text | None = None


class RefreshPrices(InputModel):
    """Which prices to download. Every security with a symbol by default."""

    security_ids: list[Id] | None = Field(default=None, max_length=MAX_LIST_LENGTH)
    history_start: Date | None = None
    """Also download the daily closing prices since this day."""


class RefreshExchangeRates(InputModel):
    """Which exchange rates to download. Every needed currency by default."""

    currencies: list[CurrencyCode] | None = Field(
        default=None, max_length=MAX_LIST_LENGTH
    )
    history_start: Date | None = None


class PriceUpdateOut(OutputModel):
    """Outcome of a refresh."""

    prices: list[PriceOut]
    exchange_rates: list[ExchangeRateOut]
    errors: list[str]


class ProviderOut(OutputModel):
    """A registered price or exchange-rate provider."""

    id: str
    name: str
    description: str


class SecurityInfoOut(OutputModel):
    """A search result from a price provider."""

    symbol: str
    name: str
    exchange: str | None
    kind: str | None
    currency: str | None
