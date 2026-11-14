"""Book-wide settings."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import MetaRow
from picciuli.errors import ValidationError
from picciuli.model import UNSET, Settings, Unset

__all__ = ["SettingsService"]

_MAX_MINOR_DIGITS = 6


def _read(session: Session) -> Settings:
    values = {row.key: row.value for row in session.scalars(select(MetaRow))}
    return Settings(
        currency=values.get("currency", "$"),
        minor_digits=int(values.get("minor_digits", "2")),
    )


def _write(session: Session, key: str, value: str) -> None:
    session.merge(MetaRow(key=key, value=value))


class SettingsService:
    """Read and change book-wide settings.

    Obtain it as [`Book.settings`][picciuli.Book.settings].
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def get(self) -> Settings:
        """Return the current settings."""
        with self._uow.session() as session:
            return _read(session)

    def update(
        self,
        *,
        currency: str | Unset = UNSET,
        minor_digits: int | Unset = UNSET,
    ) -> Settings:
        """Change settings; arguments left `UNSET` are not modified.

        Changing `minor_digits` does not rescale stored amounts: it only changes
        how user interfaces should interpret them.

        Args:
            currency: Currency symbol or code, for example `"€"` or `"EUR"`.
            minor_digits: Number of decimal digits of the currency (0 to 6).

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
        with self._uow.session() as session:
            if new_currency is not None:
                _write(session, "currency", new_currency)
            if digits is not None:
                _write(session, "minor_digits", str(digits))
            session.flush()
            return _read(session)
