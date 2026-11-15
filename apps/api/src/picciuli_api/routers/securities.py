"""Security, price and exchange-rate endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, status

from picciuli_api.deps import BookDep
from picciuli_api.schemas.investments import (
    ExchangeRateIn,
    ExchangeRateOut,
    LatestExchangeRateOut,
    LatestPriceOut,
    PriceIn,
    PriceOut,
    SecurityCreate,
    SecurityOut,
    SecurityUpdate,
)

securities = APIRouter(prefix="/securities", tags=["securities"])
rates = APIRouter(prefix="/exchange-rates", tags=["exchange rates"])


@securities.get("")
def list_securities(book: BookDep) -> list[SecurityOut]:
    """List the securities."""
    return [SecurityOut.model_validate(s) for s in book.securities.list()]


@securities.post("", status_code=status.HTTP_201_CREATED)
def create_security(book: BookDep, body: SecurityCreate) -> SecurityOut:
    """Create a security."""
    security = book.securities.create(
        body.name,
        currency=body.currency,
        kind=body.kind,
        symbol=body.symbol,
        isin=body.isin,
        notes=body.notes,
    )
    return SecurityOut.model_validate(security)


@securities.get("/{security_id}")
def get_security(book: BookDep, security_id: int) -> SecurityOut:
    """Get one security."""
    return SecurityOut.model_validate(book.securities.get(security_id))


@securities.patch("/{security_id}")
def update_security(
    book: BookDep, security_id: int, body: SecurityUpdate
) -> SecurityOut:
    """Change a security."""
    security = book.securities.update(security_id, **body.changes())
    return SecurityOut.model_validate(security)


@securities.delete("/{security_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_security(book: BookDep, security_id: int) -> None:
    """Delete a security that no transaction uses."""
    book.securities.delete(security_id)


@securities.get("/{security_id}/prices")
def list_prices(
    book: BookDep,
    security_id: int,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> list[PriceOut]:
    """Stored prices of a security, oldest first."""
    found = book.securities.prices(security_id, start=start, end=end)
    return [PriceOut.model_validate(p) for p in found]


@securities.get("/{security_id}/latest-price")
def latest_price(
    book: BookDep, security_id: int, as_of: dt.date | None = None
) -> LatestPriceOut:
    """Latest price on or before a day, also converted into the book currency."""
    price = book.securities.latest_price(security_id, as_of=as_of)
    converted = book.securities.latest_price_in_book_currency(security_id, as_of=as_of)
    return LatestPriceOut(
        price=None if price is None else PriceOut.model_validate(price),
        price_in_book_currency=converted,
    )


@securities.put("/{security_id}/prices/{date}")
def set_price(
    book: BookDep, security_id: int, date: dt.date, body: PriceIn
) -> PriceOut:
    """Store (or replace) the price of a security on a day."""
    price = book.securities.set_price(security_id, date, body.price, source=body.source)
    return PriceOut.model_validate(price)


@securities.delete(
    "/{security_id}/prices/{date}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_price(book: BookDep, security_id: int, date: dt.date) -> None:
    """Delete the price of a security on a day."""
    book.securities.delete_price(security_id, date)


@rates.get("/{currency}")
def list_exchange_rates(
    book: BookDep,
    currency: str,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> list[ExchangeRateOut]:
    """Stored rates of a currency, oldest first."""
    found = book.securities.exchange_rates(currency, start=start, end=end)
    return [ExchangeRateOut.model_validate(r) for r in found]


@rates.get("/{currency}/latest")
def latest_exchange_rate(
    book: BookDep, currency: str, as_of: dt.date | None = None
) -> LatestExchangeRateOut:
    """Latest rate of a currency on or before a day."""
    rate = book.securities.latest_exchange_rate(currency, as_of=as_of)
    return LatestExchangeRateOut(
        exchange_rate=None if rate is None else ExchangeRateOut.model_validate(rate)
    )


@rates.put("/{currency}/{date}")
def set_exchange_rate(
    book: BookDep, currency: str, date: dt.date, body: ExchangeRateIn
) -> ExchangeRateOut:
    """Store (or replace) the rate of a currency on a day."""
    rate = book.securities.set_exchange_rate(currency, date, body.rate)
    return ExchangeRateOut.model_validate(rate)
