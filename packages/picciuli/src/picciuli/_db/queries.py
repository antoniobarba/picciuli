"""Conversion from ORM rows to public dataclasses, and shared queries (private)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Iterable
from typing import TypeVar

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from picciuli.errors import NotFoundError
from picciuli.model import (
    Account,
    AccountSplit,
    AccountType,
    Budget,
    Category,
    ExternalSplit,
    Period,
    Split,
    Transaction,
)

from .tables import (
    AccountRow,
    Base,
    BudgetRow,
    CategoryRow,
    PeriodRow,
    SplitRow,
    TransactionRow,
)

RowT = TypeVar("RowT", bound=Base)


def get_row(session: Session, model: type[RowT], row_id: int, label: str) -> RowT:
    row = session.get(model, row_id)
    if row is None:
        raise NotFoundError(f"{label} {row_id} does not exist")
    return row


def to_account(row: AccountRow) -> Account:
    return Account(
        id=row.id,
        name=row.name,
        type=AccountType(row.type),
        opening_balance=row.opening_balance,
        opening_date=row.opening_date,
        goal=row.goal,
        notes=row.notes,
        position=row.position,
        closed_on=row.closed_on,
    )


def to_category(row: CategoryRow) -> Category:
    return Category(
        id=row.id,
        name=row.name,
        symbol=row.symbol,
        parent_id=row.parent_id,
        position=row.position,
    )


def to_period(row: PeriodRow) -> Period:
    return Period(id=row.id, name=row.name, start=row.start_date, end=row.end_date)


def to_budget(row: BudgetRow) -> Budget:
    return Budget(
        id=row.id,
        category_id=row.category_id,
        period_id=row.period_id,
        amount=row.amount,
    )


def to_split(row: SplitRow) -> Split:
    if row.account_id is not None:
        return AccountSplit(account_id=row.account_id, amount=row.amount, memo=row.memo)
    return ExternalSplit(amount=row.amount, category_id=row.category_id, memo=row.memo)


def to_transaction(row: TransactionRow) -> Transaction:
    return Transaction(
        id=row.id,
        date=row.date,
        description=row.description,
        notes=row.notes,
        splits=tuple(to_split(split) for split in row.splits),
    )


def account_balances(
    session: Session,
    *,
    until: dt.date | None = None,
    inclusive: bool = True,
    account_ids: Collection[int] | None = None,
) -> dict[int, int]:
    """Balance of each account, counting transactions up to `until`.

    With `inclusive=False` the day `until` itself is excluded, which gives the
    balance at the start of that day.
    """
    sums = select(SplitRow.account_id, func.sum(SplitRow.amount)).where(
        SplitRow.account_id.is_not(None)
    )
    if until is not None:
        sums = sums.join(TransactionRow, SplitRow.transaction_id == TransactionRow.id)
        sums = sums.where(
            TransactionRow.date <= until if inclusive else TransactionRow.date < until
        )
    accounts = select(AccountRow)
    if account_ids is not None:
        sums = sums.where(SplitRow.account_id.in_(account_ids))
        accounts = accounts.where(AccountRow.id.in_(account_ids))
    totals: dict[int, int] = {
        account_id: int(total)
        for account_id, total in session.execute(sums.group_by(SplitRow.account_id))
        if account_id is not None
    }
    result: dict[int, int] = {}
    for row in session.scalars(accounts):
        counted = (
            until is None
            or row.opening_date is None
            or (row.opening_date <= until if inclusive else row.opening_date < until)
        )
        result[row.id] = (row.opening_balance if counted else 0) + totals.get(row.id, 0)
    return result


def ordered_categories(session: Session) -> list[CategoryRow]:
    """All categories in display order: each top-level followed by its children."""
    rows = session.scalars(
        select(CategoryRow).order_by(CategoryRow.position, CategoryRow.id)
    ).all()
    children: dict[int, list[CategoryRow]] = {}
    for row in rows:
        if row.parent_id is not None:
            children.setdefault(row.parent_id, []).append(row)
    ordered: list[CategoryRow] = []
    for row in rows:
        if row.parent_id is None:
            ordered.append(row)
            ordered.extend(children.get(row.id, []))
    return ordered


def external_flows(
    session: Session, start: dt.date, end: dt.date | None
) -> tuple[dict[int | None, int], int, int]:
    """Net external flow by category (None = uncategorized), income and expenses."""
    positive = func.sum(case((SplitRow.amount > 0, SplitRow.amount), else_=0))
    negative = func.sum(case((SplitRow.amount < 0, SplitRow.amount), else_=0))
    statement = (
        select(SplitRow.category_id, func.sum(SplitRow.amount), positive, negative)
        .join(TransactionRow, SplitRow.transaction_id == TransactionRow.id)
        .where(SplitRow.account_id.is_(None), TransactionRow.date >= start)
        .group_by(SplitRow.category_id)
    )
    if end is not None:
        statement = statement.where(TransactionRow.date <= end)
    by_category: dict[int | None, int] = {}
    income = expenses = 0
    for category_id, net, plus, minus in session.execute(statement):
        by_category[category_id] = int(net)
        income += int(plus)
        expenses += int(minus)
    return by_category, income, expenses


def rollup(
    categories: Iterable[CategoryRow], flows: dict[int | None, int]
) -> dict[int, int]:
    """Total flow per category including the flows of its subcategories."""
    totals: dict[int, int] = {}
    rows = list(categories)
    for row in rows:
        totals[row.id] = flows.get(row.id, 0)
    for row in rows:
        if row.parent_id is not None:
            totals[row.parent_id] += flows.get(row.id, 0)
    return totals
