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
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._decimal import from_scaled, positive_decimal, to_decimal, to_scaled
from picciuli.errors import ConflictError, NotFoundError, ValidationError
from picciuli.model import (
    AccountSplit,
    AccountType,
    DebtCharge,
    DebtLinkKind,
    DebtTerms,
    ExternalSplit,
    ImportSummary,
    ScheduleFrequency,
    ScheduleMode,
    SecurityKind,
    Settings,
    Split,
    Trade,
    TradeKind,
)
from picciuli.services import debts
from picciuli.services.investments import trade_row, trade_splits
from picciuli.services.schedules import (
    _choice,
    _day_of_month,
    _every,
    _template,
)
from picciuli.services.settings import (
    _MAX_MINOR_DIGITS,
    _cost_method,
    _period_start_day,
    read_settings,
)
from picciuli.services.transactions import _security_pairs, _validated_splits

from .queries import check_holdings, external_flows, to_schedule_split, to_trade
from .schema import DEFAULT_SETTINGS
from .tables import (
    AccountRow,
    BudgetRow,
    CategoryRow,
    DebtChargeRow,
    DebtTermsRow,
    ExchangeRateRow,
    PeriodRow,
    PriceRow,
    ScheduleDebtRow,
    ScheduleRow,
    ScheduleSplitRow,
    SecurityRow,
    SplitRow,
    TradeRow,
    TransactionRow,
)
from .upload import Deadline, RawBook

if TYPE_CHECKING:
    from picciuli.book import Book

_SplitKey = tuple[int | None, int | None, int, str | None, int | None, int | None]
_TransactionKey = tuple[
    dt.date, str | None, str | None, tuple[_SplitKey, ...], Trade | None
]

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
        start_day = values.get("period_start_day", "")
        if start_day and not (start_day.isascii() and start_day.isdigit()):
            raise ValidationError("period start day must be a number")
        shift = values.get("period_weekend_shift", "1")
        if shift not in ("0", "1"):
            raise ValidationError("period weekend shift must be 0 or 1")
        return Settings(
            currency=currency,
            minor_digits=int(digits),
            currency_code=currency_code,
            cost_method=_cost_method(values.get("cost_method", "average")),
            price_provider=price_provider,
            rate_provider=rate_provider,
            period_start_day=_period_start_day(int(start_day)) if start_day else None,
            period_weekend_shift=shift == "1",
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
        # Accounts added by this import: only they take terms from the file.
        self._created: set[int] = set()

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
                period_start_day=settings.period_start_day,
                period_weekend_shift=settings.period_weekend_shift,
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
        own_terms = self._debt_terms(accounts, categories)
        schedules, added_schedules = self._schedules(accounts, categories, own_terms)
        added_transactions, duplicates = self._transactions(
            accounts, categories, securities, schedules
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
            schedules=added_schedules,
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
                self._created.add(new.id)
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

    def _debt_terms(
        self, accounts: dict[int, int], categories: dict[int, int]
    ) -> set[int]:
        """Add the terms of the accounts this import created; return them.

        An account already in the book is never changed: it keeps its own
        terms, or none, and its own credit card schedules.
        """
        imported: set[int] = set()
        charges: dict[int, list[tuple[int, DebtCharge]]] = {}
        for label, raw in self._rows("debt_charges", "debt charge"):
            with _context(label):
                _, account, position, amount, category, text = raw
                owner = _mapped_id(account, accounts, "account id", "account")
                charges.setdefault(owner, []).append(
                    (
                        v.integer(position, "position"),
                        DebtCharge(
                            v.integer(amount, "amount"),
                            _optional_mapped_id(
                                category, categories, "category id", "category"
                            ),
                            v.optional_text(text, "label"),
                        ),
                    )
                )
        with_terms: set[int] = set()
        for label, row in self._rows("debt_terms", "debt terms"):
            with _context(label):
                (
                    account,
                    rate,
                    payment,
                    percent,
                    due_day,
                    statement_day,
                    limit,
                    payer,
                    category,
                ) = row
                account_id = _mapped_id(account, accounts, "account id", "account")
                if account_id in with_terms:
                    raise ValidationError("the account has terms twice")
                with_terms.add(account_id)
                if account_id not in self._created:
                    continue
                own_charges = sorted(charges.get(account_id, []), key=lambda c: c[0])
                terms = DebtTerms(
                    annual_rate=_scaled(rate, "annual rate"),
                    payment=v.optional_integer(payment, "payment"),
                    payment_percent=None
                    if percent is None
                    else _scaled(percent, "payment percent"),
                    due_day=v.optional_integer(due_day, "due day"),
                    statement_day=v.optional_integer(statement_day, "statement day"),
                    credit_limit=v.optional_integer(limit, "credit limit"),
                    payment_account_id=_optional_mapped_id(
                        payer, accounts, "payment account id", "payment account"
                    ),
                    interest_category_id=_optional_mapped_id(
                        category, categories, "interest category id", "category"
                    ),
                    charges=tuple(charge for _, charge in own_charges),
                )
                target = self._session.get(AccountRow, account_id)
                assert target is not None
                columns, _, _ = debts.validated_terms(self._session, target, terms)
                self._session.add(DebtTermsRow(account_id=account_id, **columns))
                self._session.flush()
                self._session.expire(target, ["debt_terms"])
                imported.add(account_id)
        if set(charges) - with_terms:
            raise ValidationError(
                "the file has debt charges of an account without terms"
            )
        return imported

    def _schedules(
        self,
        accounts: dict[int, int],
        categories: dict[int, int],
        own_terms: set[int],
    ) -> tuple[dict[int, int | None], int]:
        headers: dict[int, dict[str, object]] = {}
        for label, row in self._rows("schedules", "schedule"):
            with _context(label):
                schedule_id, fields = _parse_schedule(row)
                headers[schedule_id] = fields
        links: dict[int, tuple[DebtLinkKind, int, int | None]] = {}
        for label, raw in self._rows("schedule_debts", "schedule debt"):
            with _context(label):
                owner_id, account, kind, category = raw
                owner = v.identifier(owner_id, "schedule id")
                if owner not in headers:
                    raise ValidationError("its schedule does not exist")
                link_kind = _choice(DebtLinkKind, kind, "debt kind")
                interest = _optional_mapped_id(
                    category, categories, "interest category id", "category"
                )
                if link_kind is not DebtLinkKind.LOAN_PAYMENT and interest is not None:
                    raise ValidationError("only loan payments have a category")
                links[owner] = (
                    link_kind,
                    _mapped_id(account, accounts, "account id", "account"),
                    interest,
                )
        templates: dict[int, list[tuple[int, int, Split]]] = {}
        for label, raw in self._rows("schedule_splits", "schedule split"):
            with _context(label):
                id_, owner_id, position, account, category, amount, memo = raw
                owner = v.identifier(owner_id, "schedule id")
                if owner not in headers:
                    raise ValidationError("its schedule does not exist")
                if account is not None and category is not None:
                    raise ValidationError(
                        "a split cannot have both an account and a category"
                    )
                value = v.integer(amount, "amount")
                text = v.optional_text(memo, "memo")
                split: Split = (
                    ExternalSplit(
                        value,
                        _optional_mapped_id(
                            category, categories, "category id", "category"
                        ),
                        text,
                    )
                    if account is None
                    else AccountSplit(
                        _mapped_id(account, accounts, "account id", "account"),
                        value,
                        text,
                    )
                )
                templates.setdefault(owner, []).append(
                    (
                        v.integer(position, "position"),
                        v.identifier(id_, "id"),
                        split,
                    )
                )
        existing: dict[tuple[object, ...], list[int]] = {}
        card_schedules: dict[tuple[DebtLinkKind, int], int] = {}
        for stored in self._session.scalars(
            select(ScheduleRow).order_by(ScheduleRow.id)
        ):
            values = {name: getattr(stored, name) for name in _SCHEDULE_FIELDS}
            values["paused"] = bool(stored.paused)
            link = None
            if stored.debt is not None:
                link = (
                    DebtLinkKind(stored.debt.kind),
                    stored.debt.account_id,
                    stored.debt.interest_category_id,
                )
                card_schedules.setdefault(link[:2], stored.id)
            key = _schedule_key(
                values, [to_schedule_split(s) for s in stored.splits], link
            )
            existing.setdefault(key, []).append(stored.id)
        mapping: dict[int, int | None] = {}
        added = 0
        for schedule_id in sorted(headers):
            self._deadline.check()
            fields = headers[schedule_id]
            splits = [s for _, _, s in sorted(templates.get(schedule_id, []))]
            link = links.get(schedule_id)
            card = link is not None and link[0] in debts.CARD_KINDS
            if card and link is not None and link[1] not in own_terms:
                if link[1] in self._created:
                    raise ValidationError(
                        f"schedule {schedule_id} of the file: its credit card has "
                        "no debt terms"
                    )
                # The account keeps the card schedules it had, if any.
                mapping[schedule_id] = card_schedules.get(link[:2])
                continue
            if link is not None and not card and link[1] not in self._created:
                loan = self._session.get(AccountRow, link[1])
                if loan is None or not debts.is_liability(loan) or debts.is_card(loan):
                    # An account of the book that is not a loan: a plain transfer.
                    link = None
            matches = existing.get(_schedule_key(fields, splits, link))
            if matches:
                mapping[schedule_id] = matches.pop(0)
                continue
            with _context(f"schedule {schedule_id} of the file"):
                rows: list[ScheduleSplitRow] = []
                debt_row = None
                if link is not None:
                    debt_row = ScheduleDebtRow(
                        account_id=link[1],
                        kind=link[0].value,
                        interest_category_id=link[2],
                    )
                if card and link is not None:
                    if splits:
                        raise ValidationError("credit card schedules have no splits")
                    if link[:2] in card_schedules:
                        raise ValidationError("its credit card has it twice")
                    card_account = self._session.get(AccountRow, link[1])
                    assert card_account is not None
                    debts.check_card_schedule(card_account, link[0], fields)
                else:
                    # The template is checked like a new one; the day only
                    # matters for opening dates, checked again when posting.
                    rows = _template(self._session, dt.date.max, splits)
                    if debt_row is not None:
                        debts.check_loan_template(self._session, debt_row, splits)
            new = ScheduleRow(**fields, splits=rows, debt=debt_row)
            self._session.add(new)
            self._session.flush()
            if card and link is not None:
                card_schedules[link[:2]] = new.id
            mapping[schedule_id] = new.id
            added += 1
        return mapping, added

    def _transactions(
        self,
        accounts: dict[int, int],
        categories: dict[int, int],
        securities: dict[int, int],
        schedules: dict[int, int | None],
    ) -> tuple[int, int]:
        headers: dict[int, tuple[dt.date, str | None, str | None, int | None]] = {}
        for label, row in self._rows("transactions", "transaction"):
            with _context(label):
                id_, day, description, notes, schedule_id = row
                headers[v.identifier(id_, "id")] = (
                    _date(day, "date"),
                    v.optional_text(description, "description"),
                    v.optional_text(notes, "notes"),
                    _schedule_of(schedule_id, schedules),
                )
        splits: dict[int, list[_Split]] = {}
        for label, row in self._rows("splits", "split"):
            with _context(label):
                split = _Split.parse(row)
                if split.transaction_id not in headers:
                    raise ValidationError("its transaction does not exist")
                splits.setdefault(split.transaction_id, []).append(split)
        trades: dict[int, Trade] = {}
        for label, row in self._rows("trades", "trade"):
            with _context(label):
                transaction_id, parsed = _parse_trade(
                    row, accounts, categories, securities
                )
                if transaction_id not in headers:
                    raise ValidationError("its transaction does not exist")
                trades[transaction_id] = parsed
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
                None if row.trade is None else to_trade(row.trade),
            )
            for row in self._session.scalars(select(TransactionRow))
        )
        added = duplicates = 0
        pairs: set[tuple[int, int]] = set()
        for transaction_id in sorted(headers):
            self._deadline.check()
            day, description, notes, schedule_id = headers[transaction_id]
            with _context(f"transaction {transaction_id} of the file"):
                items = sorted(
                    splits.get(transaction_id, []), key=lambda s: (s.position, s.id)
                )
                mapped = [
                    _map_split(s, accounts, categories, securities) for s in items
                ]
                trade = trades.get(transaction_id)
                if trade is not None:
                    _check_trade(trade, mapped)
                key = _transaction_key(
                    day,
                    description,
                    notes,
                    tuple(_split_key(s) for s in mapped),
                    trade,
                )
                if existing[key] > 0:
                    existing[key] -= 1
                    duplicates += 1
                    continue
                rows = _validated_splits(self._session, day, mapped)
            transaction = TransactionRow(
                date=day,
                description=description,
                notes=notes,
                schedule_id=schedule_id,
                splits=rows,
                trade=None if trade is None else trade_row(trade),
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
        book.schedules.list()
        book.debts.list()
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
    trade: Trade | None,
) -> _TransactionKey:
    return (date, description, notes, splits, trade)


_SCHEDULE_FIELDS: Final = (
    "description",
    "notes",
    "frequency",
    "every",
    "day_of_month",
    "next_date",
    "end_date",
    "remaining",
    "mode",
    "paused",
    "last_error",
)


def _parse_schedule(row: tuple[object, ...]) -> tuple[int, dict[str, object]]:
    """Identifier and validated columns of a schedule from untrusted values."""
    (
        id_,
        description,
        notes,
        frequency,
        every,
        day_of_month,
        next_date,
        end,
        remaining,
        mode,
        paused,
        last_error,
    ) = row
    kind = _choice(ScheduleFrequency, frequency, "frequency")
    if paused not in (0, 1) or isinstance(paused, float):
        raise ValidationError("paused must be 0 or 1")
    left = None if remaining is None else v.count(remaining, "remaining")
    first = _optional_date(next_date, "next date")
    last = _optional_date(end, "end")
    if first is not None:
        if last is not None and first > last:
            raise ValidationError("the next occurrence is after the end day")
        if left == 0:
            raise ValidationError("an active schedule needs occurrences left")
    return v.identifier(id_, "id"), {
        "description": v.optional_text(description, "description"),
        "notes": v.optional_text(notes, "notes"),
        "frequency": kind.value,
        "every": _every(every),
        "day_of_month": _day_of_month(kind, day_of_month, None),
        "next_date": first,
        "end_date": last,
        "remaining": left,
        "mode": _choice(ScheduleMode, mode, "mode").value,
        "paused": bool(paused),
        "last_error": v.optional_text(last_error, "last error"),
    }


def _schedule_key(
    fields: dict[str, object],
    splits: Sequence[Split],
    link: tuple[DebtLinkKind, int, int | None] | None = None,
) -> tuple[object, ...]:
    # The last error is a transient status, not part of the schedule.
    return (
        *(fields[name] for name in _SCHEDULE_FIELDS if name != "last_error"),
        tuple(_split_key(s) for s in splits),
        link,
    )


def _schedule_of(value: object, schedules: dict[int, int | None]) -> int | None:
    """The schedule of a transaction; `None` for one dropped by the import."""
    if value is None:
        return None
    schedule_id = v.identifier(value, "schedule id")
    if schedule_id not in schedules:
        raise ValidationError("its schedule does not exist")
    return schedules[schedule_id]


def _scaled(value: object, field: str) -> Decimal:
    return to_decimal(from_scaled(v.integer(value, field)), field)


def _mapped_id(value: object, ids: dict[int, int], field: str, label: str) -> int:
    mapped = ids.get(v.identifier(value, field))
    if mapped is None:
        raise ValidationError(f"its {label} does not exist")
    return mapped


def _optional_mapped_id(
    value: object, ids: dict[int, int], field: str, label: str
) -> int | None:
    return None if value is None else _mapped_id(value, ids, field, label)


def _parse_trade(
    row: tuple[object, ...],
    accounts: dict[int, int],
    categories: dict[int, int],
    securities: dict[int, int],
) -> tuple[int, Trade]:
    (
        transaction_id,
        kind,
        account,
        security,
        quantity,
        amount,
        other,
        fee,
        fee_category,
        tax,
        tax_category,
        gain_category,
    ) = row
    if kind not in ("buy", "sell"):
        raise ValidationError("kind must be 'buy' or 'sell'")
    scaled = v.integer(quantity, "quantity")
    if scaled <= 0:
        raise ValidationError("quantity must be positive")
    trade = Trade(
        kind=TradeKind(kind),
        account_id=_mapped_id(account, accounts, "account id", "account"),
        security_id=_mapped_id(security, securities, "security id", "security"),
        quantity=to_decimal(from_scaled(scaled), "quantity"),
        amount=v.positive_amount(amount, "amount"),
        other_account_id=_optional_mapped_id(
            other, accounts, "other account id", "other account"
        ),
        fee=v.non_negative_amount(fee, "fee"),
        fee_category_id=_optional_mapped_id(
            fee_category, categories, "fee category id", "fee category"
        ),
        tax=v.non_negative_amount(tax, "tax"),
        tax_category_id=_optional_mapped_id(
            tax_category, categories, "tax category id", "tax category"
        ),
        gain_category_id=_optional_mapped_id(
            gain_category, categories, "gain category id", "gain category"
        ),
    )
    if trade.kind is TradeKind.BUY and (
        trade.tax or trade.tax_category_id or trade.gain_category_id
    ):
        raise ValidationError("a purchase cannot have a tax or a gain")
    return v.identifier(transaction_id, "transaction id"), trade


def _check_trade(trade: Trade, splits: list[Split]) -> None:
    """Refuse a trade whose arguments do not produce the transaction's splits."""
    cost = -sum(
        s.amount
        for s in splits
        if isinstance(s, AccountSplit) and s.security_id is not None
    )
    expected = Counter(_split_key(s)[:3] + _split_key(s)[4:] for s in splits)
    built = Counter(
        _split_key(s)[:3] + _split_key(s)[4:] for s in trade_splits(trade, cost)
    )
    if expected != built:
        raise ValidationError("its trade does not match its splits")


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
        delete(TradeRow),
        delete(SplitRow),
        delete(TransactionRow),
        delete(ScheduleDebtRow),
        delete(ScheduleSplitRow),
        delete(ScheduleRow),
        delete(DebtChargeRow),
        delete(DebtTermsRow),
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
    tables = (
        AccountRow,
        CategoryRow,
        TransactionRow,
        SecurityRow,
        PeriodRow,
        ScheduleRow,
    )
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
