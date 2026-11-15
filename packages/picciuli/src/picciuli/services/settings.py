"""Book-wide settings."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import ExchangeRateRow, MetaRow
from picciuli.errors import ValidationError
from picciuli.model import UNSET, CostMethod, Settings, Unset

__all__ = ["SettingsService"]

_MAX_MINOR_DIGITS = 6


def read_settings(session: Session) -> Settings:
    values = {row.key: row.value for row in session.scalars(select(MetaRow))}
    code = values.get("currency_code") or None
    return Settings(
        currency=values.get("currency", "$"),
        minor_digits=int(values.get("minor_digits", "2")),
        currency_code=code,
        cost_method=CostMethod(values.get("cost_method", CostMethod.AVERAGE.value)),
        price_provider=values.get("price_provider", "yahoo"),
        rate_provider=values.get("rate_provider", "yahoo"),
    )


def _write(session: Session, key: str, value: str) -> None:
    session.merge(MetaRow(key=key, value=value))


def _cost_method(value: object) -> CostMethod:
    try:
        return CostMethod(value)
    except ValueError:
        allowed = ", ".join(m.value for m in CostMethod)
        raise ValidationError(
            f"invalid cost method {value!r}; expected one of: {allowed}"
        ) from None


class SettingsService:
    """Read and change book-wide settings.

    Obtain it as [`Book.settings`][picciuli.Book.settings].
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def get(self) -> Settings:
        """Return the current settings."""
        with self._uow.session() as session:
            return read_settings(session)

    def update(
        self,
        *,
        currency: str | Unset = UNSET,
        minor_digits: int | Unset = UNSET,
        currency_code: str | None | Unset = UNSET,
        cost_method: CostMethod | str | Unset = UNSET,
        price_provider: str | Unset = UNSET,
        rate_provider: str | Unset = UNSET,
    ) -> Settings:
        """Change settings; arguments left `UNSET` are not modified.

        Changing `minor_digits` does not rescale stored amounts: it only changes
        how user interfaces should interpret them.

        Exchange rates are relative to the book currency, so changing
        `currency_code` deletes every stored exchange rate; refresh prices
        afterwards to download rates for the new currency.

        Args:
            currency: Currency symbol or code, for example `"€"` or `"EUR"`.
            minor_digits: Number of decimal digits of the currency (0 to 6).
            currency_code: ISO 4217 code of the book currency, or `None`.
            cost_method: How the cost of sold shares is computed. It applies
                to sales recorded afterwards.
            price_provider: Identifier of a registered price provider (see
                [`available_providers`][picciuli.prices.available_providers]).
            rate_provider: Identifier of a registered exchange-rate provider
                (see
                [`available_rate_providers`][picciuli.rates.available_rate_providers]).

        Raises:
            ValidationError: If an argument is invalid.
        """
        new_currency = (
            None if isinstance(currency, Unset) else v.name(currency, "currency")
        )
        digits = None
        if not isinstance(minor_digits, Unset):
            digits = v.integer(minor_digits, "minor digits")
            if not 0 <= digits <= _MAX_MINOR_DIGITS:
                raise ValidationError(
                    f"minor digits must be between 0 and {_MAX_MINOR_DIGITS}"
                )
        new_code: str | None | Unset = UNSET
        if not isinstance(currency_code, Unset):
            new_code = (
                None
                if currency_code is None
                else v.currency_code(currency_code, "currency code")
            )
        method = None if isinstance(cost_method, Unset) else _cost_method(cost_method)
        provider = None
        if not isinstance(price_provider, Unset):
            from picciuli.prices import provider_ids

            provider = v.name(price_provider, "price provider")
            if provider not in provider_ids():
                raise ValidationError(f"unknown price provider {provider!r}")
        rates = None
        if not isinstance(rate_provider, Unset):
            from picciuli.rates import rate_provider_ids

            rates = v.name(rate_provider, "exchange-rate provider")
            if rates not in rate_provider_ids():
                raise ValidationError(f"unknown exchange-rate provider {rates!r}")
        with self._uow.session() as session:
            if new_currency is not None:
                _write(session, "currency", new_currency)
            if digits is not None:
                _write(session, "minor_digits", str(digits))
            if not isinstance(new_code, Unset):
                if new_code != read_settings(session).currency_code:
                    session.execute(delete(ExchangeRateRow))
                _write(session, "currency_code", new_code or "")
            if method is not None:
                _write(session, "cost_method", method.value)
            if provider is not None:
                _write(session, "price_provider", provider)
            if rates is not None:
                _write(session, "rate_provider", rates)
            session.flush()
            return read_settings(session)
