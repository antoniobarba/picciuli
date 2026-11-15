"""Import the rows of one book into another, enforcing every domain rule (private).

The rows come from `picciuli._db.upload` as unvalidated tuples, possibly from
an attacker-controlled file. Every value is type-checked and every entity is
re-created through the public services (or their validators) inside the
caller's transaction, so an import can never store data the services would
refuse: unbalanced splits, negative holdings, transactions on closed accounts
or before an opening date, shares in non-investment accounts, invalid settings
or dangling references.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._decimal import from_scaled, positive_decimal, to_decimal, to_scaled
from picciuli.errors import ConflictError, NotFoundError, ValidationError
from picciuli.model import (
    AccountSplit,
    AccountType,
    ExternalSplit,
    ImportSummary,
    SecurityKind,
    Settings,
    Split,
)
from picciuli.services.settings import (
    _MAX_MINOR_DIGITS,
    _cost_method,
    read_settings,
)
from picciuli.services.transactions import _security_pairs, _validated_splits

from .queries import check_holdings, external_flows
from .schema import DEFAULT_SETTINGS
from .tables import (
    AccountRow,
    BudgetRow,
    CategoryRow,
    ExchangeRateRow,
    PeriodRow,
    PriceRow,
    SecurityRow,
    SplitRow,
    TransactionRow,
)
from .upload import Deadline, RawBook

if TYPE_CHECKING:
    from picciuli.book import Book

_SplitKey = tuple[int | None, int | None, int, str | None, int | None, int | None]
_TransactionKey = tuple[dt.date, str | None, str | None, tuple[_SplitKey, ...]]

_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MAX_SQL_INTEGER: Final = 2**63 - 1
_BATCH: Final = 5000
_SETTING_KEYS: Final = frozenset({"schema_version", *DEFAULT_SETTINGS})


def import_book(
    book: Book, session: Session, raw: RawBook, *, replace: bool, deadline: Deadline
) -> ImportSummary:
    """Add the content of `raw` to `book`, inside the active `session`.

    With `replace`, the book is emptied first and takes the source settings.
    Otherwise entities are matched by name (accounts, categories, securities,
    also by ISIN), by day (prices, rates), by range (periods) or by content
    (transactions), and only the missing ones are added.
    """
    return _Importer(book, session, raw, deadline).run(replace=replace)


# --- Validation of raw values -----------------------------------------------


def _date(value: object, field: str) -> dt.date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValidationError(f"{field} must be a date written as YYYY-MM-DD")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{field} is not a valid date") from None


def _optional_date(value: object, field: str) -> dt.date | None:
    return None if value is None else _date(value, field)


def _row_id(row: tuple[object, ...]) -> object:
    return row[0] if row else None


@contextlib.contextmanager
def _context(label: str) -> Iterator[None]:
    """Prefix errors caused by the source data with the row they come from."""
    try:
        yield
    except (ValidationError, NotFoundError) as exc:
        raise ValidationError(f"{label}: {exc}") from None


def _settings(rows: Sequence[tuple[object, ...]]) -> Settings:
    values: dict[str, str] = {}
    for key, value in rows:
        if not isinstance(key, str) or key not in _SETTING_KEYS:
            raise ValidationError(f"unknown setting {key!r}")
        if not isinstance(value, str):
            raise ValidationError(f"setting {key!r} must be text")
        values[key] = value
    from picciuli.prices import provider_ids
    from picciuli.rates import rate_provider_ids

    # Missing keys get the same defaults as `read_settings`.
    with _context("settings"):
        currency = v.name(values.get("currency", "$"), "currency")
        digits = values.get("minor_digits", "2")
        if not (digits.isascii() and digits.isdigit()) or not (
            0 <= int(digits) <= _MAX_MINOR_DIGITS
        ):
            raise ValidationError(
                f"minor digits must be between 0 and {_MAX_MINOR_DIGITS}"
            )
        code = values.get("currency_code") or None
        currency_code = None if code is None else v.currency_code(code, "currency code")
        price_provider = v.name(values.get("price_provider", "yahoo"), "price provider")
        if price_provider not in provider_ids():
            raise ValidationError(f"unknown price provider {price_provider!r}")
        rate_provider = v.name(
            values.get("rate_provider", "yahoo"), "exchange-rate provider"
        )
        if rate_provider not in rate_provider_ids():
            raise ValidationError(f"unknown exchange-rate provider {rate_provider!r}")
        return Settings(
            currency=currency,
            minor_digits=int(digits),
            currency_code=currency_code,
            cost_method=_cost_method(values.get("cost_method", "average")),
            price_provider=price_provider,
            rate_provider=rate_provider,
        )


@dataclass(frozen=True, slots=True)
class _Account:
    id: int
    name: str
    type: AccountType
    opening_balance: int
    opening_date: dt.date | None
    goal: int | None
    notes: str | None
    position: int
    closed_on: dt.date | None

    @classmethod
    def parse(cls, row: tuple[object, ...]) -> _Account:
        id_, name, type_, opening, opened, goal, notes, position, closed = row
        try:
            account_type = AccountType(type_)
        except ValueError:
            raise ValidationError(f"invalid account type {type_!r}") from None
        account = cls(
            id=v.identifier(id_, "id"),
            name=v.name(name, "account name"),
            type=account_type,
            opening_balance=v.integer(opening, "opening balance"),
            opening_date=_optional_date(opened, "opening date"),
            goal=v.optional_integer(goal, "goal"),
            notes=v.optional_text(notes, "notes"),
            position=v.integer(position, "position"),
            closed_on=_optional_date(closed, "closing date"),
        )
        if (
            account.closed_on is not None
            and account.opening_date is not None
            and account.closed_on < account.opening_date
        ):
            raise ValidationError("the closing date is before the opening date")
        return account


@dataclass(frozen=True, slots=True)
class _Category:
    id: int
    name: str
    symbol: str
    parent_id: int | None
    position: int

    @classmethod
    def parse(cls, row: tuple[object, ...]) -> _Category:
        id_, name, symbol, parent_id, position = row
        if not isinstance(symbol, str):
            raise ValidationError("category symbol must be a string")
        return cls(
            id=v.identifier(id_, "id"),
            name=v.name(name, "category name"),
            symbol=symbol,
            parent_id=v.optional_integer(parent_id, "parent id"),
            position=v.integer(position, "position"),
        )


@dataclass(frozen=True, slots=True)
class _Security:
    id: int
    name: str
    symbol: str | None
    isin: str | None
    currency: str
    kind: SecurityKind
    notes: str | None

    @classmethod
    def parse(cls, row: tuple[object, ...]) -> _Security:
        id_, name, symbol, isin, currency, kind, notes = row
        try:
            security_kind = SecurityKind(kind)
        except ValueError:
            raise ValidationError(f"invalid security kind {kind!r}") from None
        return cls(
            id=v.identifier(id_, "id"),
            name=v.name(name, "security name"),
            symbol=v.optional_text(symbol, "symbol"),
            isin=v.isin(isin),
            currency=v.currency_code(currency),
            kind=security_kind,
            notes=v.optional_text(notes, "notes"),
        )


@dataclass(frozen=True, slots=True)
class _Split:
    id: int
    transaction_id: int
    position: int
    account_id: int | None
    category_id: int | None
    amount: int
    memo: str | None
    security_id: int | None
    quantity: int | None

    @classmethod
    def parse(cls, row: tuple[object, ...]) -> _Split:
        id_, tx, position, account, category, amount, memo, security, quantity = row
        split = cls(
            id=v.identifier(id_, "id"),
            transaction_id=v.identifier(tx, "transaction id"),
            position=v.integer(position, "position"),
            account_id=v.optional_integer(account, "account id"),
            category_id=v.optional_integer(category, "category id"),
            amount=v.integer(amount, "amount"),
            memo=v.optional_text(memo, "memo"),
            security_id=v.optional_integer(security, "security id"),
            quantity=v.optional_integer(quantity, "quantity"),
        )
        if split.account_id is not None and split.category_id is not None:
            raise ValidationError("a split cannot have both an account and a category")
        if (split.security_id is None) != (split.quantity is None):
            raise ValidationError("a split needs both a security and a quantity")
        if split.security_id is not None and split.account_id is None:
            raise ValidationError("only account splits can move shares")
        return split


# --- The import itself --------------------------------------------------------


class _Importer:
    def __init__(
        self, book: Book, session: Session, raw: RawBook, deadline: Deadline
    ) -> None:
        self._book = book
        self._session = session
        self._raw = raw
        self._deadline = deadline

    def _rows(self, table: str, label: str) -> Iterator[tuple[str, tuple[object, ...]]]:
        """Rows of a source table, with a label for error messages."""
        for row in self._raw[table]:
            self._deadline.check()
            yield f"{label} {_row_id(row)!r} of the file", row

    def run(self, *, replace: bool) -> ImportSummary:
        settings = _settings(self._raw["meta"])
        if replace:
            _wipe(self._session)
        if replace or _is_empty(self._session):
            self._book.settings.update(
                currency=settings.currency,
                minor_digits=settings.minor_digits,
                currency_code=settings.currency_code,
                cost_method=settings.cost_method,
                price_provider=settings.price_provider,
                rate_provider=settings.rate_provider,
            )
        else:
            _check_compatible(read_settings(self._session), settings)
        accounts, added_accounts, to_close = self._accounts()
        categories, added_categories = self._categories()
        securities, added_securities = self._securities()
        periods, added_periods = self._periods()
        prices = self._prices(securities)
        exchange_rates = self._exchange_rates()
        budgets = self._budgets(categories, periods)
        added_transactions, duplicates = self._transactions(
            accounts, categories, securities
        )
        self._close(to_close)
        self._read_back()
        return ImportSummary(
            replaced=replace,
            accounts=added_accounts,
            categories=added_categories,
            securities=added_securities,
            prices=prices,
            exchange_rates=exchange_rates,
            periods=added_periods,
            budgets=budgets,
            transactions=added_transactions,
            duplicates=duplicates,
        )

    def _accounts(
        self,
    ) -> tuple[dict[int, int], int, list[tuple[int, _Account]]]:
        parsed = []
        for label, row in self._rows("accounts", "account"):
            with _context(label):
                parsed.append(_Account.parse(row))
        by_name = {
            row.name.casefold(): row.id
            for row in self._session.scalars(select(AccountRow))
        }
        mapping: dict[int, int] = {}
        to_close: list[tuple[int, _Account]] = []
        added = 0
        for account in sorted(parsed, key=lambda a: (a.position, a.id)):
            self._deadline.check()
            key = account.name.casefold()
            if key not in by_name:
                with _context(f"account {account.name!r} of the file"):
                    new = self._book.accounts.create(
                        account.name,
                        account.type,
                        opening_balance=account.opening_balance,
                        opening_date=account.opening_date,
                        goal=account.goal,
                        notes=account.notes,
                    )
                by_name[key] = new.id
                added += 1
                if account.closed_on is not None:
                    to_close.append((new.id, account))
            mapping[account.id] = by_name[key]
        return mapping, added, to_close

    def _categories(self) -> tuple[dict[int, int], int]:
        parsed: dict[int, _Category] = {}
        for label, row in self._rows("categories", "category"):
            with _context(label):
                category = _Category.parse(row)
                parsed[category.id] = category
        for category in parsed.values():
            if category.parent_id is None:
                continue
            source_parent = parsed.get(category.parent_id)
            label = f"category {category.name!r} of the file"
            if source_parent is None:
                raise ValidationError(f"{label}: its parent does not exist")
            if source_parent.parent_id is not None:
                raise ValidationError(
                    f"{label}: subcategories cannot have subcategories"
                )
        existing = list(self._session.scalars(select(CategoryRow)))
        by_name = {row.name.casefold(): row.id for row in existing}
        parent_of = {row.id: row.parent_id for row in existing}
        mapping: dict[int, int] = {}
        added = 0
        # Parents first, so that children can be attached to them.
        for category in sorted(
            parsed.values(),
            key=lambda c: (c.parent_id is not None, c.position, c.id),
        ):
            self._deadline.check()
            key = category.name.casefold()
            if key not in by_name:
                parent = (
                    None if category.parent_id is None else mapping[category.parent_id]
                )
                # The tree has two levels: if the matched parent is a subcategory
                # here, nest under its own parent instead.
                if parent is not None and parent_of[parent] is not None:
                    parent = parent_of[parent]
                with _context(f"category {category.name!r} of the file"):
                    new = self._book.categories.create(
                        category.name, parent_id=parent, symbol=category.symbol
                    )
                by_name[key] = new.id
                parent_of[new.id] = parent
                added += 1
            mapping[category.id] = by_name[key]
        return mapping, added

    def _securities(self) -> tuple[dict[int, int], int]:
        parsed = []
        for label, row in self._rows("securities", "security"):
            with _context(label):
                parsed.append(_Security.parse(row))
        existing = list(self._session.scalars(select(SecurityRow)))
        by_isin = {row.isin: row.id for row in existing if row.isin}
        by_name = {row.name.casefold(): row.id for row in existing}
        mapping: dict[int, int] = {}
        added = 0
        for security in sorted(parsed, key=lambda s: s.id):
            self._deadline.check()
            key = security.name.casefold()
            found = by_isin.get(security.isin) if security.isin else None
            if found is None:
                found = by_name.get(key)
            if found is None:
                with _context(f"security {security.name!r} of the file"):
                    new = self._book.securities.create(
                        security.name,
                        currency=security.currency,
                        kind=security.kind,
                        symbol=security.symbol,
                        isin=security.isin,
                        notes=security.notes,
                    )
                found = by_name[key] = new.id
                if security.isin:
                    by_isin[security.isin] = new.id
                added += 1
            mapping[security.id] = found
        return mapping, added

    def _prices(self, securities: dict[int, int]) -> int:
        known = {
            (security_id, day)
            for security_id, day in self._session.execute(
                select(PriceRow.security_id, PriceRow.date)
            )
        }
        new: list[dict[str, object]] = []
        added = 0
        for label, row in self._rows("prices", "price"):
            with _context(label):
                _id, security_id, day, price, source = row
                security = securities.get(v.identifier(security_id, "security id"))
                if security is None:
                    raise ValidationError("its security does not exist")
                date = _date(day, "date")
                scaled = v.integer(price, "price")
                positive_decimal(from_scaled(scaled), "price")
                text = v.optional_text(source, "source")
            key = (security, date)
            if key in known:
                continue
            known.add(key)
            new.append(
                {"security_id": security, "date": date, "price": scaled, "source": text}
            )
            added += 1
            self._insert(PriceRow, new)
        self._insert(PriceRow, new, final=True)
        return added

    def _exchange_rates(self) -> int:
        known = {
            (currency, day)
            for currency, day in self._session.execute(
                select(ExchangeRateRow.currency, ExchangeRateRow.date)
            )
        }
        new: list[dict[str, object]] = []
        added = 0
        for label, row in self._rows("exchange_rates", "exchange rate"):
            with _context(label):
                _id, currency, day, rate = row
                code = v.currency_code(currency)
                date = _date(day, "date")
                scaled = v.integer(rate, "rate")
                positive_decimal(from_scaled(scaled), "rate")
            key = (code, date)
            if key in known:
                continue
            known.add(key)
            new.append({"currency": code, "date": date, "rate": scaled})
            added += 1
            self._insert(ExchangeRateRow, new)
        self._insert(ExchangeRateRow, new, final=True)
        return added

    def _insert(
        self,
        table: type[PriceRow | ExchangeRateRow],
        rows: list[dict[str, object]],
        *,
        final: bool = False,
    ) -> None:
        """Insert validated rows in batches, emptying `rows`."""
        if rows and (final or len(rows) >= _BATCH):
            self._session.execute(insert(table), rows)
            rows.clear()

    def _periods(self) -> tuple[dict[int, int], int]:
        parsed = []
        for label, row in self._rows("periods", "period"):
            with _context(label):
                id_, name, start, end = row
                first = _date(start, "start")
                last = _optional_date(end, "end")
                v.date_range(first, last)
                parsed.append(
                    (first, v.identifier(id_, "id"), v.name(name, "period name"), last)
                )
        by_range = {
            (row.start_date, row.end_date): row.id
            for row in self._session.scalars(
                select(PeriodRow).order_by(PeriodRow.id.desc())
            )
        }
        mapping: dict[int, int] = {}
        added = 0
        # Rows are added directly, not with PeriodService.create, because an
        # import must not end the open-ended periods already in the book.
        for start, period_id, name, end in sorted(parsed, key=lambda p: p[:2]):
            self._deadline.check()
            key = (start, end)
            if key not in by_range:
                new = PeriodRow(name=name, start_date=start, end_date=end)
                self._session.add(new)
                self._session.flush()
                by_range[key] = new.id
                added += 1
            mapping[period_id] = by_range[key]
        return mapping, added

    def _budgets(self, categories: dict[int, int], periods: dict[int, int]) -> int:
        known = {
            (category_id, period_id)
            for category_id, period_id in self._session.execute(
                select(BudgetRow.category_id, BudgetRow.period_id)
            )
        }
        added = 0
        for label, row in self._rows("budgets", "budget"):
            with _context(label):
                _id, category_id, period_id, amount = row
                category = categories.get(v.identifier(category_id, "category id"))
                period = periods.get(v.identifier(period_id, "period id"))
                if category is None or period is None:
                    raise ValidationError("its category or period does not exist")
                value = v.integer(amount, "budget amount")
                key = (category, period)
                if key in known:
                    continue
                known.add(key)
                self._book.budgets.create(category, period, value)
                added += 1
        return added

    def _transactions(
        self,
        accounts: dict[int, int],
        categories: dict[int, int],
        securities: dict[int, int],
    ) -> tuple[int, int]:
        headers: dict[int, tuple[dt.date, str | None, str | None]] = {}
        for label, row in self._rows("transactions", "transaction"):
            with _context(label):
                id_, day, description, notes = row
                headers[v.identifier(id_, "id")] = (
                    _date(day, "date"),
                    v.optional_text(description, "description"),
                    v.optional_text(notes, "notes"),
                )
        splits: dict[int, list[_Split]] = {}
        for label, row in self._rows("splits", "split"):
            with _context(label):
                split = _Split.parse(row)
                if split.transaction_id not in headers:
                    raise ValidationError("its transaction does not exist")
                splits.setdefault(split.transaction_id, []).append(split)
        # The identity map only keeps weak references: holding the rows used by
        # the split validation avoids one query (and autoflush) per transaction.
        pinned = [
            *self._session.scalars(select(AccountRow)),
            *self._session.scalars(select(CategoryRow)),
            *self._session.scalars(select(SecurityRow)),
        ]

        existing = Counter(
            _transaction_key(
                row.date,
                row.description,
                row.notes,
                tuple(_row_split_key(s) for s in row.splits),
            )
            for row in self._session.scalars(select(TransactionRow))
        )
        added = duplicates = 0
        pairs: set[tuple[int, int]] = set()
        for transaction_id in sorted(headers):
            self._deadline.check()
            day, description, notes = headers[transaction_id]
            with _context(f"transaction {transaction_id} of the file"):
                items = sorted(
                    splits.get(transaction_id, []), key=lambda s: (s.position, s.id)
                )
                mapped = [
                    _map_split(s, accounts, categories, securities) for s in items
                ]
                key = _transaction_key(
                    day, description, notes, tuple(_split_key(s) for s in mapped)
                )
                if existing[key] > 0:
                    existing[key] -= 1
                    duplicates += 1
                    continue
                rows = _validated_splits(self._session, day, mapped)
            transaction = TransactionRow(
                date=day, description=description, notes=notes, splits=rows
            )
            self._session.add(transaction)
            pairs |= _security_pairs(rows)
            added += 1
            if added % _BATCH == 0:
                self._session.flush()
        self._session.flush()
        pinned.clear()
        self._check_totals()
        self._deadline.check()
        check_holdings(self._session, pairs)
        return added, duplicates

    def _check_totals(self) -> None:
        # SQLite sums amounts in 64-bit integers and fails on overflow: keep the
        # sum of the absolute amounts below the limit so that every partial sum
        # computed by a report stays valid.
        total = 0
        for (amount,) in self._session.execute(select(SplitRow.amount)):
            total += abs(amount)
        if total > _MAX_SQL_INTEGER:
            raise ValidationError(
                "the amounts are too large: their total would overflow"
            )

    def _close(self, to_close: list[tuple[int, _Account]]) -> None:
        for account_id, account in to_close:
            self._deadline.check()
            assert account.closed_on is not None
            label = f"account {account.name!r} of the file"
            try:
                self._book.accounts.close(account_id, on=account.closed_on)
            except (ConflictError, ValidationError, NotFoundError) as exc:
                raise ValidationError(f"{label}: cannot be closed: {exc}") from None

    def _read_back(self) -> None:
        """Compute every derived figure once, so that a broken book never commits."""
        self._deadline.check()
        book = self._book
        book.settings.get()
        book.accounts.balances(include_closed=True)
        book.accounts.net_worth()
        book.categories.list()
        book.periods.list()
        book.budgets.list()
        book.securities.list()
        book.investments.valuations(include_closed=True)
        book.investments.net_worth()
        external_flows(self._session, dt.date.min, None)
        self._deadline.check()


def _map_split(
    split: _Split,
    accounts: dict[int, int],
    categories: dict[int, int],
    securities: dict[int, int],
) -> Split:
    if split.account_id is None:
        category = None
        if split.category_id is not None:
            category = categories.get(split.category_id)
            if category is None:
                raise ValidationError(f"split {split.id}: its category does not exist")
        return ExternalSplit(amount=split.amount, category_id=category, memo=split.memo)
    account = accounts.get(split.account_id)
    if account is None:
        raise ValidationError(f"split {split.id}: its account does not exist")
    security = quantity = None
    if split.security_id is not None:
        security = securities.get(split.security_id)
        if security is None:
            raise ValidationError(f"split {split.id}: its security does not exist")
        assert split.quantity is not None
        if split.quantity == 0:
            raise ValidationError(f"split {split.id}: the quantity cannot be zero")
        quantity = to_decimal(from_scaled(split.quantity), f"split {split.id} quantity")
    return AccountSplit(
        account_id=account,
        amount=split.amount,
        memo=split.memo,
        security_id=security,
        quantity=quantity,
    )


def _transaction_key(
    date: dt.date,
    description: str | None,
    notes: str | None,
    splits: tuple[_SplitKey, ...],
) -> _TransactionKey:
    return (date, description, notes, splits)


def _split_key(split: Split) -> _SplitKey:
    if isinstance(split, ExternalSplit):
        return (None, split.category_id, split.amount, split.memo, None, None)
    quantity = None if split.quantity is None else to_scaled(split.quantity)
    return (
        split.account_id,
        None,
        split.amount,
        split.memo,
        split.security_id,
        quantity,
    )


def _row_split_key(row: SplitRow) -> _SplitKey:
    return (
        row.account_id,
        row.category_id,
        row.amount,
        row.memo,
        row.security_id,
        row.quantity,
    )


def _wipe(session: Session) -> None:
    for statement in (
        delete(SplitRow),
        delete(TransactionRow),
        delete(BudgetRow),
        delete(PeriodRow),
        delete(PriceRow),
        delete(ExchangeRateRow),
        delete(SecurityRow),
        delete(CategoryRow).where(CategoryRow.parent_id.is_not(None)),
        delete(CategoryRow),
        delete(AccountRow),
    ):
        session.execute(statement)


def _is_empty(session: Session) -> bool:
    tables = (AccountRow, CategoryRow, TransactionRow, SecurityRow, PeriodRow)
    return all(session.scalar(select(t.id).limit(1)) is None for t in tables)


def _check_compatible(target: Settings, source: Settings) -> None:
    if target.currency_code and source.currency_code:
        same_currency = target.currency_code == source.currency_code
        mine, theirs = target.currency_code, source.currency_code
    else:
        same_currency = target.currency.strip() == source.currency.strip()
        mine, theirs = target.currency, source.currency
    if not same_currency:
        raise ConflictError(
            f"cannot merge data in {theirs} into a book in {mine}; "
            "replace the data instead, or change the currency first"
        )
    if target.minor_digits != source.minor_digits:
        raise ConflictError(
            f"cannot merge amounts with {source.minor_digits} decimal digits into "
            f"a book with {target.minor_digits}; replace the data instead"
        )
