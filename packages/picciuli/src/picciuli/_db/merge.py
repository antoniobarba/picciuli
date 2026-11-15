"""Copy the content of one database into another (private)."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from picciuli._db.tables import (
    AccountRow,
    BudgetRow,
    CategoryRow,
    ExchangeRateRow,
    MetaRow,
    PeriodRow,
    PriceRow,
    SecurityRow,
    SplitRow,
    TransactionRow,
)
from picciuli.errors import ConflictError
from picciuli.model import ImportSummary, Settings
from picciuli.services.settings import read_settings

_SplitKey = tuple[int | None, int | None, int, str | None, int | None, int | None]
_TransactionKey = tuple[dt.date, str | None, str | None, tuple[_SplitKey, ...]]


def import_book(target: Session, source: Session, *, replace: bool) -> ImportSummary:
    """Copy everything stored in `source` into `target`.

    With `replace`, the target is emptied first and takes the source settings.
    Otherwise entities are matched by name (accounts, categories, securities,
    also by ISIN), by day (prices, rates), by range (periods) or by content
    (transactions), and only the missing ones are added.
    """
    if replace:
        _wipe(target)
    if replace or _is_empty(target):
        _copy_settings(target, source)
    else:
        _check_compatible(read_settings(target), read_settings(source))
    accounts, added_accounts = _accounts(target, source)
    categories, added_categories = _categories(target, source)
    securities, added_securities = _securities(target, source)
    periods, added_periods = _periods(target, source)
    added_transactions, duplicates = _transactions(
        target, source, accounts, categories, securities
    )
    summary = ImportSummary(
        replaced=replace,
        accounts=added_accounts,
        categories=added_categories,
        securities=added_securities,
        prices=_prices(target, source, securities),
        exchange_rates=_exchange_rates(target, source),
        periods=added_periods,
        budgets=_budgets(target, source, categories, periods),
        transactions=added_transactions,
        duplicates=duplicates,
    )
    target.flush()
    return summary


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


def _copy_settings(target: Session, source: Session) -> None:
    for row in source.scalars(select(MetaRow).where(MetaRow.key != "schema_version")):
        target.merge(MetaRow(key=row.key, value=row.value))


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


def _accounts(target: Session, source: Session) -> tuple[dict[int, int], int]:
    by_name = {
        row.name.casefold(): row.id for row in target.scalars(select(AccountRow))
    }
    position = target.scalar(select(func.max(AccountRow.position))) or 0
    mapping: dict[int, int] = {}
    added = 0
    for row in source.scalars(
        select(AccountRow).order_by(AccountRow.position, AccountRow.id)
    ):
        key = row.name.casefold()
        if key not in by_name:
            position += 1
            new = AccountRow(
                name=row.name,
                type=row.type,
                opening_balance=row.opening_balance,
                opening_date=row.opening_date,
                goal=row.goal,
                notes=row.notes,
                position=position,
                closed_on=row.closed_on,
            )
            target.add(new)
            target.flush()
            by_name[key] = new.id
            added += 1
        mapping[row.id] = by_name[key]
    return mapping, added


def _categories(target: Session, source: Session) -> tuple[dict[int, int], int]:
    existing = list(target.scalars(select(CategoryRow)))
    by_name = {row.name.casefold(): row.id for row in existing}
    parent_of = {row.id: row.parent_id for row in existing}
    last: dict[int | None, int] = {}
    for row in existing:
        last[row.parent_id] = max(last.get(row.parent_id, 0), row.position)
    # Parents first, so that children can be attached to them.
    rows = sorted(
        source.scalars(select(CategoryRow)),
        key=lambda r: (r.parent_id is not None, r.position, r.id),
    )
    mapping: dict[int, int] = {}
    added = 0
    for row in rows:
        key = row.name.casefold()
        if key not in by_name:
            parent = None if row.parent_id is None else mapping.get(row.parent_id)
            # The tree has two levels: if the matched parent is a subcategory
            # here, nest under its own parent instead.
            if parent is not None and parent_of[parent] is not None:
                parent = parent_of[parent]
            last[parent] = last.get(parent, 0) + 1
            new = CategoryRow(
                name=row.name,
                symbol=row.symbol,
                parent_id=parent,
                position=last[parent],
            )
            target.add(new)
            target.flush()
            by_name[key] = new.id
            parent_of[new.id] = parent
            added += 1
        mapping[row.id] = by_name[key]
    return mapping, added


def _securities(target: Session, source: Session) -> tuple[dict[int, int], int]:
    existing = list(target.scalars(select(SecurityRow)))
    by_isin = {row.isin: row.id for row in existing if row.isin}
    by_name = {row.name.casefold(): row.id for row in existing}
    mapping: dict[int, int] = {}
    added = 0
    for row in source.scalars(select(SecurityRow).order_by(SecurityRow.id)):
        key = row.name.casefold()
        found = by_isin.get(row.isin) if row.isin else None
        if found is None:
            found = by_name.get(key)
        if found is None:
            new = SecurityRow(
                name=row.name,
                symbol=row.symbol,
                isin=row.isin,
                currency=row.currency,
                kind=row.kind,
                notes=row.notes,
            )
            target.add(new)
            target.flush()
            found = by_name[key] = new.id
            if row.isin:
                by_isin[row.isin] = new.id
            added += 1
        mapping[row.id] = found
    return mapping, added


def _prices(target: Session, source: Session, securities: dict[int, int]) -> int:
    known = {
        tuple(row)
        for row in target.execute(select(PriceRow.security_id, PriceRow.date))
    }
    added = 0
    for row in source.scalars(select(PriceRow).order_by(PriceRow.id)):
        key = (securities[row.security_id], row.date)
        if key in known:
            continue
        known.add(key)
        target.add(
            PriceRow(
                security_id=key[0], date=row.date, price=row.price, source=row.source
            )
        )
        added += 1
    return added


def _exchange_rates(target: Session, source: Session) -> int:
    known = {
        tuple(row)
        for row in target.execute(
            select(ExchangeRateRow.currency, ExchangeRateRow.date)
        )
    }
    added = 0
    for row in source.scalars(select(ExchangeRateRow).order_by(ExchangeRateRow.id)):
        key = (row.currency, row.date)
        if key in known:
            continue
        known.add(key)
        target.add(ExchangeRateRow(currency=row.currency, date=row.date, rate=row.rate))
        added += 1
    return added


def _periods(target: Session, source: Session) -> tuple[dict[int, int], int]:
    by_range = {
        (row.start_date, row.end_date): row.id
        for row in target.scalars(select(PeriodRow).order_by(PeriodRow.id.desc()))
    }
    mapping: dict[int, int] = {}
    added = 0
    for row in source.scalars(
        select(PeriodRow).order_by(PeriodRow.start_date, PeriodRow.id)
    ):
        key = (row.start_date, row.end_date)
        if key not in by_range:
            new = PeriodRow(
                name=row.name, start_date=row.start_date, end_date=row.end_date
            )
            target.add(new)
            target.flush()
            by_range[key] = new.id
            added += 1
        mapping[row.id] = by_range[key]
    return mapping, added


def _budgets(
    target: Session,
    source: Session,
    categories: dict[int, int],
    periods: dict[int, int],
) -> int:
    known = {
        tuple(row)
        for row in target.execute(select(BudgetRow.category_id, BudgetRow.period_id))
    }
    added = 0
    for row in source.scalars(select(BudgetRow).order_by(BudgetRow.id)):
        key = (categories[row.category_id], periods[row.period_id])
        if key in known:
            continue
        known.add(key)
        target.add(BudgetRow(category_id=key[0], period_id=key[1], amount=row.amount))
        added += 1
    return added


def _transaction_key(
    date: dt.date,
    description: str | None,
    notes: str | None,
    splits: Iterable[_SplitKey],
) -> _TransactionKey:
    return (date, description, notes, tuple(splits))


def _split_key(row: SplitRow) -> _SplitKey:
    return (
        row.account_id,
        row.category_id,
        row.amount,
        row.memo,
        row.security_id,
        row.quantity,
    )


def _transactions(
    target: Session,
    source: Session,
    accounts: dict[int, int],
    categories: dict[int, int],
    securities: dict[int, int],
) -> tuple[int, int]:
    existing = Counter(
        _transaction_key(
            row.date, row.description, row.notes, (_split_key(s) for s in row.splits)
        )
        for row in target.scalars(select(TransactionRow))
    )
    added = duplicates = 0
    for row in source.scalars(select(TransactionRow).order_by(TransactionRow.id)):
        splits = [
            SplitRow(
                position=split.position,
                account_id=None
                if split.account_id is None
                else accounts[split.account_id],
                category_id=(
                    None if split.category_id is None else categories[split.category_id]
                ),
                amount=split.amount,
                memo=split.memo,
                security_id=(
                    None if split.security_id is None else securities[split.security_id]
                ),
                quantity=split.quantity,
            )
            for split in row.splits
        ]
        key = _transaction_key(
            row.date, row.description, row.notes, (_split_key(s) for s in splits)
        )
        if existing[key] > 0:
            existing[key] -= 1
            duplicates += 1
            continue
        target.add(
            TransactionRow(
                date=row.date,
                description=row.description,
                notes=row.notes,
                splits=splits,
            )
        )
        added += 1
    return added, duplicates
