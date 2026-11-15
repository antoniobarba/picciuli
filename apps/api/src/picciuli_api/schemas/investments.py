"""Bodies of the security, price, exchange-rate and investment endpoints."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import Field

from picciuli import SecurityKind

from .accounts import AccountOut
from .base import DecimalStr, InputModel, OutputModel, PatchModel

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

    name: str = Field(examples=["Vanguard FTSE All-World"])
    currency: str = Field(examples=["EUR"])
    kind: SecurityKind = SecurityKind.STOCK
    symbol: str | None = Field(default=None, examples=["VWCE.DE"])
    isin: str | None = Field(default=None, examples=["IE00BK5BQT80"])
    notes: str | None = None


class SecurityUpdate(PatchModel):
    """Changes to a security."""

    name: str | None = None
    currency: str | None = None
    kind: SecurityKind | None = None
    symbol: str | None = None
    isin: str | None = None
    notes: str | None = None


class PriceOut(OutputModel):
    """The price of one share on a day, in the security's currency."""

    security_id: int
    date: dt.date
    price: DecimalStr
    source: str | None


class PriceIn(InputModel):
    """A price entered by hand."""

    price: Decimal = Field(gt=0, examples=["112.34"])
    source: str | None = None


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

    rate: Decimal = Field(gt=0, examples=["0.92"])


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

    date: dt.date
    account_id: int
    security_id: int
    quantity: Decimal = Field(examples=["1.5"])
    cost: int = Field(description="Price paid for the shares, in minor units.")
    from_account_id: int | None = None
    fee: int = 0
    fee_category_id: int | None = None
    description: str | None = None
    notes: str | None = None


class SellCreate(InputModel):
    """A sale of shares."""

    date: dt.date
    account_id: int
    security_id: int
    quantity: Decimal = Field(examples=["1.5"])
    proceeds: int = Field(description="Gross sale proceeds, in minor units.")
    to_account_id: int | None = None
    fee: int = 0
    fee_category_id: int | None = None
    tax: int = 0
    tax_category_id: int | None = None
    gain_category_id: int | None = None
    description: str | None = None
    notes: str | None = None


class RefreshPrices(InputModel):
    """Which prices to download. Every security with a symbol by default."""

    security_ids: list[int] | None = None
    history_start: dt.date | None = None
    """Also download the daily closing prices since this day."""


class RefreshExchangeRates(InputModel):
    """Which exchange rates to download. Every needed currency by default."""

    currencies: list[str] | None = None
    history_start: dt.date | None = None


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
