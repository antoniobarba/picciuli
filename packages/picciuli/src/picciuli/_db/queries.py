"""Conversion from ORM rows to public dataclasses, and shared queries (private)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Final, TypeVar

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import QueryableAttribute, Session

from picciuli._decimal import from_scaled
from picciuli.errors import NotFoundError, ValidationError
from picciuli.limits import MAX_ID
from picciuli.model import (
    Account,
    AccountSplit,
    AccountType,
    Budget,
    Category,
    DebtCharge,
    DebtLinkKind,
    DebtTerms,
    ExchangeRate,
    ExternalSplit,
    GoalPriority,
    Period,
    Price,
    SavingsGoal,
    Schedule,
    ScheduleDebt,
    ScheduleFrequency,
    ScheduleMode,
    Security,
    SecurityKind,
    Split,
    Trade,
    TradeKind,
    Transaction,
)

from .tables import (
    AccountRow,
    Base,
    BudgetRow,
    CategoryRow,
    ExchangeRateRow,
    PeriodRow,
    PriceRow,
    SavingsGoalRow,
    ScheduleRow,
    ScheduleSplitRow,
    SecurityRow,
    SplitRow,
    TradeRow,
    TransactionRow,
)

RowT = TypeVar("RowT", bound=Base)

_HALF_BITS: Final = 32
_LOW_MASK: Final = (1 << _HALF_BITS) - 1


def get_row(session: Session, model: type[RowT], row_id: int, label: str) -> RowT:
    # Larger integers cannot be stored, and would overflow the SQLite binding.
    in_range = not isinstance(row_id, int) or -MAX_ID - 1 <= row_id <= MAX_ID
    row = session.get(model, row_id) if in_range else None
    if row is None:
        raise NotFoundError(f"{label} {row_id} does not exist")
    return row


def to_debt_terms(row: AccountRow) -> DebtTerms | None:
    terms = row.debt_terms
    if terms is None:
        return None
    kinds = {link.kind for link in row.debt_links}
    return DebtTerms(
        annual_rate=from_scaled(terms.annual_rate),
        payment=terms.payment,
        payment_percent=None
        if terms.payment_percent is None
        else from_scaled(terms.payment_percent),
        due_day=terms.due_day,
        statement_day=terms.statement_day,
        credit_limit=terms.credit_limit,
        payment_account_id=terms.payment_account_id,
        interest_category_id=terms.interest_category_id,
        propose_interest=DebtLinkKind.CARD_INTEREST.value in kinds,
        propose_minimum=DebtLinkKind.CARD_MIN_PAYMENT.value in kinds,
        charges=tuple(
            DebtCharge(c.amount, c.category_id, c.label) for c in terms.charges
        ),
    )


def to_account(row: AccountRow) -> Account:
    return Account(
        id=row.id,
        name=row.name,
        type=AccountType(row.type),
        opening_balance=row.opening_balance,
        opening_date=row.opening_date,
        notes=row.notes,
        position=row.position,
        closed_on=row.closed_on,
        debt_terms=to_debt_terms(row),
    )


def to_goal(row: SavingsGoalRow) -> SavingsGoal:
    return SavingsGoal(
        id=row.id,
        account_id=row.account_id,
        name=row.name,
        target_amount=row.target_amount,
        saved_amount=row.saved_amount,
        target_date=row.target_date,
        priority=GoalPriority(row.priority),
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
        return AccountSplit(
            account_id=row.account_id,
            amount=row.amount,
            memo=row.memo,
            security_id=row.security_id,
            quantity=None if row.quantity is None else from_scaled(row.quantity),
        )
    return ExternalSplit(amount=row.amount, category_id=row.category_id, memo=row.memo)


def to_security(row: SecurityRow) -> Security:
    return Security(
        id=row.id,
        name=row.name,
        symbol=row.symbol,
        isin=row.isin,
        currency=row.currency,
        kind=SecurityKind(row.kind),
        notes=row.notes,
    )


def to_price(row: PriceRow) -> Price:
    return Price(
        security_id=row.security_id,
        date=row.date,
        price=from_scaled(row.price),
        source=row.source,
    )


def to_exchange_rate(row: ExchangeRateRow) -> ExchangeRate:
    return ExchangeRate(
        currency=row.currency, date=row.date, rate=from_scaled(row.rate)
    )


def to_trade(row: TradeRow) -> Trade:
    return Trade(
        kind=TradeKind(row.kind),
        account_id=row.account_id,
        security_id=row.security_id,
        quantity=from_scaled(row.quantity),
        amount=row.amount,
        other_account_id=row.other_account_id,
        fee=row.fee,
        fee_category_id=row.fee_category_id,
        tax=row.tax,
        tax_category_id=row.tax_category_id,
        gain_category_id=row.gain_category_id,
    )


def to_transaction(row: TransactionRow) -> Transaction:
    return Transaction(
        id=row.id,
        date=row.date,
        description=row.description,
        notes=row.notes,
        splits=tuple(to_split(split) for split in row.splits),
        trade=None if row.trade is None else to_trade(row.trade),
        schedule_id=row.schedule_id,
    )


def to_schedule_split(row: ScheduleSplitRow) -> Split:
    if row.account_id is not None:
        return AccountSplit(account_id=row.account_id, amount=row.amount, memo=row.memo)
    return ExternalSplit(amount=row.amount, category_id=row.category_id, memo=row.memo)


def to_schedule(row: ScheduleRow) -> Schedule:
    return Schedule(
        id=row.id,
        description=row.description,
        notes=row.notes,
        splits=tuple(to_schedule_split(split) for split in row.splits),
        frequency=ScheduleFrequency(row.frequency),
        every=row.every,
        day_of_month=row.day_of_month,
        next_date=row.next_date,
        end=row.end_date,
        remaining=row.remaining,
        mode=ScheduleMode(row.mode),
        paused=bool(row.paused),
        last_error=row.last_error,
        debt=None
        if row.debt is None
        else ScheduleDebt(
            kind=DebtLinkKind(row.debt.kind),
            account_id=row.debt.account_id,
            interest_category_id=row.debt.interest_category_id,
        ),
    )


def _exact_sum(
    value: ColumnElement[int] | QueryableAttribute[int],
) -> tuple[ColumnElement[int], ColumnElement[int]]:
    """Aggregate a SUM that cannot overflow, in two parts for `_combine`.

    SQLite raises "integer overflow" when a SUM leaves the 64-bit range, which
    would make a whole book unreadable. Summing the high and low 32 bits
    separately is exact for any stored integer and cannot overflow.
    """
    return (
        func.sum(value.op(">>")(_HALF_BITS)),
        func.sum(value.op("&")(_LOW_MASK)),
    )


def _combine(high: int | None, low: int | None) -> int:
    return (int(high or 0) << _HALF_BITS) + int(low or 0)


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
    sums = select(SplitRow.account_id, *_exact_sum(SplitRow.amount)).where(
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
        account_id: _combine(high, low)
        for account_id, high, low in session.execute(sums.group_by(SplitRow.account_id))
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


def daily_account_flows(session: Session) -> dict[int, list[tuple[dt.date, int]]]:
    """Net change of each account per day with transactions, in date order."""
    statement = (
        select(SplitRow.account_id, TransactionRow.date, *_exact_sum(SplitRow.amount))
        .join(TransactionRow, SplitRow.transaction_id == TransactionRow.id)
        .where(SplitRow.account_id.is_not(None))
        .group_by(SplitRow.account_id, TransactionRow.date)
        .order_by(SplitRow.account_id, TransactionRow.date)
    )
    result: dict[int, list[tuple[dt.date, int]]] = {}
    for account_id, day, high, low in session.execute(statement):
        if account_id is not None:
            result.setdefault(account_id, []).append((day, _combine(high, low)))
    return result


@dataclass(frozen=True, slots=True)
class ShareMove:
    """One split moving shares, with its quantity still scaled."""

    date: dt.date
    transaction_id: int
    account_id: int
    security_id: int
    quantity: int
    amount: int


def share_moves(
    session: Session,
    *,
    account_id: int | None = None,
    security_id: int | None = None,
    until: dt.date | None = None,
    excluding: int | None = None,
) -> list[ShareMove]:
    """Splits moving shares in chronological order, optionally filtered.

    `excluding` leaves out the moves of one transaction.
    """
    statement = (
        select(
            TransactionRow.date,
            TransactionRow.id,
            SplitRow.account_id,
            SplitRow.security_id,
            SplitRow.quantity,
            SplitRow.amount,
        )
        .join(TransactionRow, SplitRow.transaction_id == TransactionRow.id)
        .where(SplitRow.security_id.is_not(None))
        .order_by(TransactionRow.date, TransactionRow.id, SplitRow.position)
    )
    if account_id is not None:
        statement = statement.where(SplitRow.account_id == account_id)
    if security_id is not None:
        statement = statement.where(SplitRow.security_id == security_id)
    if until is not None:
        statement = statement.where(TransactionRow.date <= until)
    if excluding is not None:
        statement = statement.where(TransactionRow.id != excluding)
    moves = []
    for day, tx_id, acc, sec, qty, amount in session.execute(statement):
        # The query only selects account splits that move shares.
        if acc is None or sec is None or qty is None:
            raise RuntimeError(f"transaction {tx_id} has an incomplete share move")
        moves.append(ShareMove(day, tx_id, acc, sec, qty, amount))
    return moves


def check_holdings(session: Session, pairs: Iterable[tuple[int, int]]) -> None:
    """Reject share quantities that would become negative at the end of a day.

    Args:
        session: Session with the pending changes flushed.
        pairs: `(account_id, security_id)` pairs whose history changed.
    """
    session.flush()
    for account_id, security_id in set(pairs):
        held = 0
        moves = share_moves(session, account_id=account_id, security_id=security_id)
        for index, move in enumerate(moves):
            held += move.quantity
            last_of_day = index + 1 == len(moves) or moves[index + 1].date != move.date
            if last_of_day and held < 0:
                security = get_row(session, SecurityRow, security_id, "security")
                account = get_row(session, AccountRow, account_id, "account")
                raise ValidationError(
                    f"account {account.name!r} would hold "
                    f"{from_scaled(held)} shares of {security.name!r} on "
                    f"{move.date.isoformat()}; quantities cannot be negative"
                )


def latest_prices(
    session: Session, *, as_of: dt.date | None = None
) -> dict[int, PriceRow]:
    """Most recent price row of each security on or before `as_of`."""
    newest = select(PriceRow.security_id, func.max(PriceRow.date).label("day"))
    if as_of is not None:
        newest = newest.where(PriceRow.date <= as_of)
    sub = newest.group_by(PriceRow.security_id).subquery()
    statement = select(PriceRow).join(
        sub, (PriceRow.security_id == sub.c.security_id) & (PriceRow.date == sub.c.day)
    )
    return {row.security_id: row for row in session.scalars(statement)}


def latest_rates(
    session: Session, *, as_of: dt.date | None = None
) -> dict[str, ExchangeRateRow]:
    """Most recent exchange rate row of each currency on or before `as_of`."""
    newest = select(
        ExchangeRateRow.currency, func.max(ExchangeRateRow.date).label("day")
    )
    if as_of is not None:
        newest = newest.where(ExchangeRateRow.date <= as_of)
    sub = newest.group_by(ExchangeRateRow.currency).subquery()
    statement = select(ExchangeRateRow).join(
        sub,
        (ExchangeRateRow.currency == sub.c.currency)
        & (ExchangeRateRow.date == sub.c.day),
    )
    return {row.currency: row for row in session.scalars(statement)}


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
    """Net external flow by category (None = uncategorized), income and expenses.

    Each category counts by its net flow, so a refund or reimbursement reduces
    the spending of its category instead of counting as income. Uncategorized
    splits have nothing in common, so each counts by its own sign.
    """
    positive = case((SplitRow.amount > 0, SplitRow.amount), else_=0)
    negative = case((SplitRow.amount < 0, SplitRow.amount), else_=0)
    statement = (
        select(
            SplitRow.category_id,
            *_exact_sum(SplitRow.amount),
            *_exact_sum(positive),
            *_exact_sum(negative),
        )
        .join(TransactionRow, SplitRow.transaction_id == TransactionRow.id)
        .where(SplitRow.account_id.is_(None), TransactionRow.date >= start)
        .group_by(SplitRow.category_id)
    )
    if end is not None:
        statement = statement.where(TransactionRow.date <= end)
    by_category: dict[int | None, int] = {}
    income = expenses = 0
    for category_id, *parts in session.execute(statement):
        net = by_category[category_id] = _combine(parts[0], parts[1])
        if category_id is None:
            income += _combine(parts[2], parts[3])
            expenses += _combine(parts[4], parts[5])
        elif net > 0:
            income += net
        else:
            expenses += net
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
