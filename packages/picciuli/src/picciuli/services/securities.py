"""Securities, their prices and exchange rates."""

from __future__ import annotations

import builtins
import datetime as dt
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._db.queries import (
    get_row,
    latest_prices,
    latest_rates,
    to_exchange_rate,
    to_price,
    to_security,
)
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import ExchangeRateRow, PriceRow, SecurityRow, SplitRow
from picciuli._decimal import positive_decimal, to_scaled
from picciuli.errors import ConflictError, NotFoundError, ValidationError
from picciuli.model import (
    UNSET,
    ExchangeRate,
    Price,
    Security,
    SecurityKind,
    Unset,
)

__all__ = ["SecurityService"]


def _kind(value: object) -> SecurityKind:
    try:
        return SecurityKind(value)
    except ValueError:
        allowed = ", ".join(k.value for k in SecurityKind)
        raise ValidationError(
            f"invalid security kind {value!r}; expected one of: {allowed}"
        ) from None


def _ensure_unique(
    session: Session, name: str, isin: str | None, exclude: int | None = None
) -> None:
    folded = name.casefold()
    for row in session.scalars(select(SecurityRow)):
        if row.id == exclude:
            continue
        if row.name.casefold() == folded:
            raise ConflictError(f"a security named {row.name!r} already exists")
        if isin is not None and row.isin == isin:
            raise ConflictError(f"security {row.name!r} already has ISIN {isin}")


def store_price(
    session: Session,
    security_id: int,
    day: dt.date,
    price: Decimal,
    source: str | None,
) -> PriceRow:
    """Insert or replace the price of a security on a day."""
    row = session.scalar(
        select(PriceRow).where(
            PriceRow.security_id == security_id, PriceRow.date == day
        )
    )
    if row is None:
        row = PriceRow(security_id=security_id, date=day)
        session.add(row)
    row.price = to_scaled(price)
    row.source = source
    session.flush()
    return row


def store_rate(
    session: Session, currency: str, day: dt.date, rate: Decimal
) -> ExchangeRateRow:
    """Insert or replace the exchange rate of a currency on a day."""
    row = session.scalar(
        select(ExchangeRateRow).where(
            ExchangeRateRow.currency == currency, ExchangeRateRow.date == day
        )
    )
    if row is None:
        row = ExchangeRateRow(currency=currency, date=day)
        session.add(row)
    row.rate = to_scaled(rate)
    session.flush()
    return row


class SecurityService:
    """Manage securities, their prices and exchange rates.

    Obtain it as [`Book.securities`][picciuli.Book.securities].

    Prices are normally downloaded with
    [`InvestmentService.refresh_prices`][picciuli.services.InvestmentService.refresh_prices],
    but can be entered by hand. A security has at most one price per day, and an
    exchange rate at most one value per currency and day; setting a value again
    replaces it.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(
        self,
        name: str,
        *,
        currency: str,
        kind: SecurityKind | str = SecurityKind.STOCK,
        symbol: str | None = None,
        isin: str | None = None,
        notes: str | None = None,
    ) -> Security:
        """Create a security.

        Args:
            name: Unique name (case-insensitive).
            currency: ISO 4217 code of the currency it is quoted in.
            kind: Kind of security.
            symbol: Symbol of the price provider, for example `"VWCE.DE"`.
            isin: ISIN, checked for validity and uniqueness.
            notes: Free text.

        Raises:
            ValidationError: If an argument is invalid.
            ConflictError: If the name or the ISIN is already used.
        """
        name = v.name(name, "security name")
        currency = v.currency_code(currency)
        security_kind = _kind(kind)
        symbol = v.optional_text(symbol, "symbol")
        code = v.isin(isin)
        notes = v.optional_text(notes, "notes")
        with self._uow.session() as session:
            _ensure_unique(session, name, code)
            row = SecurityRow(
                name=name,
                symbol=symbol,
                isin=code,
                currency=currency,
                kind=security_kind.value,
                notes=notes,
            )
            session.add(row)
            session.flush()
            return to_security(row)

    def get(self, security_id: int) -> Security:
        """Return a security.

        Raises:
            NotFoundError: If the security does not exist.
        """
        with self._uow.session() as session:
            return to_security(get_row(session, SecurityRow, security_id, "security"))

    def list(self) -> builtins.list[Security]:
        """Return every security, sorted by name."""
        with self._uow.session() as session:
            rows = session.scalars(select(SecurityRow))
            return sorted(
                (to_security(row) for row in rows), key=lambda s: s.name.casefold()
            )

    def update(
        self,
        security_id: int,
        *,
        name: str | Unset = UNSET,
        currency: str | Unset = UNSET,
        kind: SecurityKind | str | Unset = UNSET,
        symbol: str | None | Unset = UNSET,
        isin: str | None | Unset = UNSET,
        notes: str | None | Unset = UNSET,
    ) -> Security:
        """Change a security; arguments left `UNSET` are not modified.

        Changing the currency does not convert stored prices.

        Raises:
            NotFoundError: If the security does not exist.
            ValidationError: If an argument is invalid.
            ConflictError: If the name or the ISIN is already used.
        """
        with self._uow.session() as session:
            row = get_row(session, SecurityRow, security_id, "security")
            new_name = row.name if isinstance(name, Unset) else v.name(name, "name")
            new_isin = row.isin if isinstance(isin, Unset) else v.isin(isin)
            _ensure_unique(session, new_name, new_isin, exclude=row.id)
            row.name = new_name
            row.isin = new_isin
            if not isinstance(currency, Unset):
                row.currency = v.currency_code(currency)
            if not isinstance(kind, Unset):
                row.kind = _kind(kind).value
            if not isinstance(symbol, Unset):
                row.symbol = v.optional_text(symbol, "symbol")
            if not isinstance(notes, Unset):
                row.notes = v.optional_text(notes, "notes")
            session.flush()
            return to_security(row)

    def delete(self, security_id: int) -> None:
        """Delete a security and its prices.

        Raises:
            NotFoundError: If the security does not exist.
            ConflictError: If transactions move shares of it.
        """
        with self._uow.session() as session:
            row = get_row(session, SecurityRow, security_id, "security")
            used = session.scalar(
                select(func.count())
                .select_from(SplitRow)
                .where(SplitRow.security_id == row.id)
            )
            if used:
                raise ConflictError(f"security {row.name!r} is used by transactions")
            session.delete(row)

    def set_price(
        self,
        security_id: int,
        date: dt.date,
        price: Decimal | int,
        *,
        source: str | None = None,
    ) -> Price:
        """Store the price of one share on a day, replacing any existing one.

        Args:
            security_id: The security.
            date: Day of the price.
            price: Positive price in major units of the security's currency,
                with at most 8 decimal places.
            source: Origin of the price; `None` for a manual entry.

        Raises:
            NotFoundError: If the security does not exist.
            ValidationError: If an argument is invalid.
        """
        day = v.date(date, "date")
        value = positive_decimal(price, "price")
        source = v.optional_text(source, "source")
        with self._uow.session() as session:
            get_row(session, SecurityRow, security_id, "security")
            return to_price(store_price(session, security_id, day, value, source))

    def delete_price(self, security_id: int, date: dt.date) -> None:
        """Delete the price of a security on a day.

        Raises:
            NotFoundError: If there is no such price.
        """
        day = v.date(date, "date")
        with self._uow.session() as session:
            result = session.execute(
                delete(PriceRow).where(
                    PriceRow.security_id == security_id, PriceRow.date == day
                )
            )
            if not result.rowcount:  # type: ignore[attr-defined]
                raise NotFoundError(
                    f"security {security_id} has no price on {day.isoformat()}"
                )

    def prices(
        self,
        security_id: int,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> builtins.list[Price]:
        """Return the stored prices of a security in chronological order.

        Raises:
            NotFoundError: If the security does not exist.
            ValidationError: If `start` is after `end`.
        """
        start = v.optional_date(start, "start")
        end = v.optional_date(end, "end")
        v.date_range(start, end)
        statement = (
            select(PriceRow)
            .where(PriceRow.security_id == security_id)
            .order_by(PriceRow.date)
        )
        if start is not None:
            statement = statement.where(PriceRow.date >= start)
        if end is not None:
            statement = statement.where(PriceRow.date <= end)
        with self._uow.session() as session:
            get_row(session, SecurityRow, security_id, "security")
            return [to_price(row) for row in session.scalars(statement)]

    def latest_price(
        self, security_id: int, *, as_of: dt.date | None = None
    ) -> Price | None:
        """Return the most recent price on or before `as_of`, or `None`.

        Raises:
            NotFoundError: If the security does not exist.
        """
        as_of = v.optional_date(as_of, "as_of")
        with self._uow.session() as session:
            get_row(session, SecurityRow, security_id, "security")
            row = latest_prices(session, as_of=as_of).get(security_id)
            return None if row is None else to_price(row)

    def set_exchange_rate(
        self, currency: str, date: dt.date, rate: Decimal | int
    ) -> ExchangeRate:
        """Store the value of one unit of `currency` in the book currency.

        Args:
            currency: ISO 4217 code of the foreign currency.
            date: Day of the rate.
            rate: Positive rate with at most 8 decimal places, for example
                `Decimal("0.92")` euros per dollar in a euro book.

        Raises:
            ValidationError: If an argument is invalid.
        """
        code = v.currency_code(currency)
        day = v.date(date, "date")
        value = positive_decimal(rate, "rate")
        with self._uow.session() as session:
            return to_exchange_rate(store_rate(session, code, day, value))

    def exchange_rates(
        self,
        currency: str,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> builtins.list[ExchangeRate]:
        """Return the stored rates of a currency in chronological order.

        Raises:
            ValidationError: If an argument is invalid.
        """
        code = v.currency_code(currency)
        start = v.optional_date(start, "start")
        end = v.optional_date(end, "end")
        v.date_range(start, end)
        statement = (
            select(ExchangeRateRow)
            .where(ExchangeRateRow.currency == code)
            .order_by(ExchangeRateRow.date)
        )
        if start is not None:
            statement = statement.where(ExchangeRateRow.date >= start)
        if end is not None:
            statement = statement.where(ExchangeRateRow.date <= end)
        with self._uow.session() as session:
            return [to_exchange_rate(row) for row in session.scalars(statement)]

    def latest_exchange_rate(
        self, currency: str, *, as_of: dt.date | None = None
    ) -> ExchangeRate | None:
        """Return the most recent rate on or before `as_of`, or `None`.

        Raises:
            ValidationError: If an argument is invalid.
        """
        code = v.currency_code(currency)
        as_of = v.optional_date(as_of, "as_of")
        with self._uow.session() as session:
            row = latest_rates(session, as_of=as_of).get(code)
            return None if row is None else to_exchange_rate(row)
