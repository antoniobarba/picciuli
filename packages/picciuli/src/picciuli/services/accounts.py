"""Accounts: creation, lifecycle, balances, net worth and registers."""

from __future__ import annotations

import builtins
import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._db.queries import (
    account_balances,
    get_row,
    share_moves,
    to_account,
    to_transaction,
)
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import AccountRow, SplitRow, TradeRow, TransactionRow
from picciuli.errors import ConflictError, ValidationError
from picciuli.model import (
    UNSET,
    Account,
    AccountBalance,
    AccountClass,
    AccountType,
    NetWorth,
    Register,
    RegisterEntry,
    Unset,
)

__all__ = ["AccountService"]


def _account_type(value: object) -> AccountType:
    try:
        return AccountType(value)
    except ValueError:
        allowed = ", ".join(t.value for t in AccountType)
        raise ValidationError(
            f"invalid account type {value!r}; expected one of: {allowed}"
        ) from None


def _ensure_unique_name(
    session: Session, name: str, exclude: int | None = None
) -> None:
    folded = name.casefold()
    for row_id, existing in session.execute(select(AccountRow.id, AccountRow.name)):
        if row_id != exclude and existing.casefold() == folded:
            raise ConflictError(f"an account named {existing!r} already exists")


def _first_transaction_date(session: Session, account_id: int) -> dt.date | None:
    return session.scalar(
        select(func.min(TransactionRow.date))
        .join(SplitRow, SplitRow.transaction_id == TransactionRow.id)
        .where(SplitRow.account_id == account_id)
    )


def _last_transaction_date(session: Session, account_id: int) -> dt.date | None:
    return session.scalar(
        select(func.max(TransactionRow.date))
        .join(SplitRow, SplitRow.transaction_id == TransactionRow.id)
        .where(SplitRow.account_id == account_id)
    )


def _holds_securities(session: Session, account_id: int) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(SplitRow)
            .where(SplitRow.account_id == account_id, SplitRow.security_id.is_not(None))
        )
    )


class AccountService:
    """Manage accounts and compute their balances.

    Obtain it as [`Book.accounts`][picciuli.Book.accounts].

    Account balances are derived, never stored: the balance on a day is the
    opening balance (if it applies on that day) plus every account split dated on
    or before that day.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(
        self,
        name: str,
        type: AccountType | str,
        *,
        opening_balance: int = 0,
        opening_date: dt.date | None = None,
        goal: int | None = None,
        notes: str | None = None,
    ) -> Account:
        """Create an account at the end of the display order.

        Args:
            name: Unique name (case-insensitive).
            type: Account type, as an enum member or its string value.
            opening_balance: Balance before any transaction, in minor units.
                Use a negative value for money owed on a liability.
            opening_date: First day of the account; `None` means the opening
                balance applies since the beginning of time.
            goal: Optional target balance in minor units.
            notes: Optional free text.

        Returns:
            The new account.

        Raises:
            ValidationError: If an argument is invalid.
            ConflictError: If the name is already used.
        """
        name = v.name(name, "account name")
        account_type = _account_type(type)
        opening_balance = v.amount(opening_balance, "opening balance")
        opening_date = v.optional_date(opening_date, "opening date")
        goal = v.optional_amount(goal, "goal")
        notes = v.optional_text(notes, "notes")
        with self._uow.session() as session:
            _ensure_unique_name(session, name)
            last = session.scalar(select(func.max(AccountRow.position))) or 0
            row = AccountRow(
                name=name,
                type=account_type.value,
                opening_balance=opening_balance,
                opening_date=opening_date,
                goal=goal,
                notes=notes,
                position=last + 1,
                closed_on=None,
            )
            session.add(row)
            session.flush()
            return to_account(row)

    def get(self, account_id: int) -> Account:
        """Return an account.

        Raises:
            NotFoundError: If the account does not exist.
        """
        with self._uow.session() as session:
            return to_account(get_row(session, AccountRow, account_id, "account"))

    def list(self, *, include_closed: bool = True) -> builtins.list[Account]:
        """Return accounts in display order.

        Args:
            include_closed: Whether to include closed accounts.
        """
        statement = select(AccountRow).order_by(AccountRow.position, AccountRow.id)
        if not include_closed:
            statement = statement.where(AccountRow.closed_on.is_(None))
        with self._uow.session() as session:
            return [to_account(row) for row in session.scalars(statement)]

    def update(
        self,
        account_id: int,
        *,
        name: str | Unset = UNSET,
        type: AccountType | str | Unset = UNSET,
        opening_balance: int | Unset = UNSET,
        opening_date: dt.date | None | Unset = UNSET,
        goal: int | None | Unset = UNSET,
        notes: str | None | Unset = UNSET,
    ) -> Account:
        """Change account properties; arguments left `UNSET` are not modified.

        The opening balance and date of a closed account cannot change, because
        closed accounts must keep a zero balance.

        Raises:
            NotFoundError: If the account does not exist.
            ValidationError: If an argument is invalid, or the new opening date
                is later than an existing transaction of the account.
            ConflictError: If the name is already used, the opening values of
                a closed account would change, or an account with security
                transactions would stop being an investment account.
        """
        with self._uow.session() as session:
            row = get_row(session, AccountRow, account_id, "account")
            if not isinstance(name, Unset):
                new_name = v.name(name, "account name")
                _ensure_unique_name(session, new_name, exclude=row.id)
                row.name = new_name
            if not isinstance(type, Unset):
                new_type = _account_type(type)
                if new_type is not AccountType.INVESTMENT and _holds_securities(
                    session, row.id
                ):
                    raise ConflictError(
                        f"account {row.name!r} has security transactions and must "
                        "stay an investment account"
                    )
                row.type = new_type.value
            if not isinstance(goal, Unset):
                row.goal = v.optional_amount(goal, "goal")
            if not isinstance(notes, Unset):
                row.notes = v.optional_text(notes, "notes")
            changes_opening = not isinstance(opening_balance, Unset) or not isinstance(
                opening_date, Unset
            )
            if changes_opening and row.closed_on is not None:
                raise ConflictError("reopen the account to change its opening values")
            if not isinstance(opening_balance, Unset):
                row.opening_balance = v.amount(opening_balance, "opening balance")
            if not isinstance(opening_date, Unset):
                new_date = v.optional_date(opening_date, "opening date")
                first = _first_transaction_date(session, row.id)
                if new_date is not None and first is not None and first < new_date:
                    raise ValidationError(
                        f"the account has transactions on {first.isoformat()}, "
                        "before the new opening date"
                    )
                row.opening_date = new_date
            session.flush()
            return to_account(row)

    def move(self, account_id: int, position: int) -> Account:
        """Move an account to a new 1-based display position.

        Raises:
            NotFoundError: If the account does not exist.
            ValidationError: If the position is out of range.
        """
        with self._uow.session() as session:
            row = get_row(session, AccountRow, account_id, "account")
            rows = [
                r
                for r in session.scalars(
                    select(AccountRow).order_by(AccountRow.position, AccountRow.id)
                )
                if r.id != row.id
            ]
            rows.insert(v.position(position, len(rows) + 1) - 1, row)
            for index, item in enumerate(rows, start=1):
                item.position = index
            session.flush()
            return to_account(row)

    def close(self, account_id: int, *, on: dt.date | None = None) -> Account:
        """Close (archive) an account.

        A closed account keeps its history but accepts no new transactions, and
        transactions involving it cannot be edited or deleted until it is
        reopened. Its balance must be zero on the closing day: record a final
        transfer or adjustment first.

        Args:
            account_id: Account to close.
            on: Closing day; defaults to today.

        Raises:
            NotFoundError: If the account does not exist.
            ValidationError: If the day is before the opening date.
            ConflictError: If the account is already closed, has transactions
                after the closing day, has a non-zero balance or still holds
                shares.
        """
        day = v.optional_date(on, "closing date") or dt.date.today()
        with self._uow.session() as session:
            row = get_row(session, AccountRow, account_id, "account")
            if row.closed_on is not None:
                raise ConflictError(f"account {row.name!r} is already closed")
            if row.opening_date is not None and day < row.opening_date:
                raise ValidationError("the closing date is before the opening date")
            last = _last_transaction_date(session, row.id)
            if last is not None and last > day:
                raise ConflictError(
                    f"the account has transactions after {day.isoformat()}"
                )
            balance = account_balances(session, account_ids=[row.id])[row.id]
            if balance != 0:
                raise ConflictError(
                    f"the account balance must be zero to close it (it is {balance})"
                )
            held: dict[int, int] = {}
            for move in share_moves(session, account_id=row.id):
                held[move.security_id] = held.get(move.security_id, 0) + move.quantity
            if any(held.values()):
                raise ConflictError("sell or move every share before closing")
            row.closed_on = day
            session.flush()
            return to_account(row)

    def reopen(self, account_id: int) -> Account:
        """Reopen a closed account.

        Raises:
            NotFoundError: If the account does not exist.
            ConflictError: If the account is not closed.
        """
        with self._uow.session() as session:
            row = get_row(session, AccountRow, account_id, "account")
            if row.closed_on is None:
                raise ConflictError(f"account {row.name!r} is not closed")
            row.closed_on = None
            session.flush()
            return to_account(row)

    def delete(self, account_id: int) -> None:
        """Delete an account that has never been used by a transaction.

        Accounts with history should be [closed][picciuli.services.AccountService.close]
        instead.

        Raises:
            NotFoundError: If the account does not exist.
            ConflictError: If transactions reference the account.
        """
        with self._uow.session() as session:
            row = get_row(session, AccountRow, account_id, "account")
            used = session.scalar(
                select(func.count())
                .select_from(SplitRow)
                .where(SplitRow.account_id == row.id)
            ) or session.scalar(
                select(func.count())
                .select_from(TradeRow)
                .where(TradeRow.other_account_id == row.id)
            )
            if used:
                raise ConflictError(
                    f"account {row.name!r} has transactions; close it instead"
                )
            session.delete(row)
            session.flush()
            for index, item in enumerate(
                session.scalars(
                    select(AccountRow).order_by(AccountRow.position, AccountRow.id)
                ),
                start=1,
            ):
                item.position = index

    def balance(self, account_id: int, *, as_of: dt.date | None = None) -> int:
        """Return the balance of an account at the end of a day.

        For an investment account this is the ledger balance (cash plus the
        cost of the shares); see
        [`InvestmentService.valuation`][picciuli.services.InvestmentService.valuation]
        for the market value.

        Args:
            account_id: The account.
            as_of: Day to compute the balance for; `None` includes every
                transaction, including future-dated ones.

        Raises:
            NotFoundError: If the account does not exist.
        """
        as_of = v.optional_date(as_of, "as_of")
        with self._uow.session() as session:
            get_row(session, AccountRow, account_id, "account")
            return account_balances(session, until=as_of, account_ids=[account_id])[
                account_id
            ]

    def balances(
        self, *, as_of: dt.date | None = None, include_closed: bool = False
    ) -> builtins.list[AccountBalance]:
        """Return the balance of every account, in display order.

        Args:
            as_of: Day to compute balances for; `None` includes every transaction.
            include_closed: Whether to include accounts closed on or before
                `as_of` (or closed at all when `as_of` is `None`).
        """
        as_of = v.optional_date(as_of, "as_of")
        with self._uow.session() as session:
            balances = account_balances(session, until=as_of)
            rows = session.scalars(
                select(AccountRow).order_by(AccountRow.position, AccountRow.id)
            )
            result = []
            for row in rows:
                closed = row.closed_on is not None and (
                    as_of is None or row.closed_on <= as_of
                )
                if closed and not include_closed:
                    continue
                result.append(AccountBalance(to_account(row), balances[row.id]))
            return result

    def net_worth(self, *, as_of: dt.date | None = None) -> NetWorth:
        """Return total assets, liabilities and net worth at the end of a day.

        Args:
            as_of: Day to compute the totals for; `None` includes every
                transaction.
        """
        as_of = v.optional_date(as_of, "as_of")
        assets = liabilities = 0
        with self._uow.session() as session:
            balances = account_balances(session, until=as_of)
            for row in session.scalars(select(AccountRow)):
                if AccountType(row.type).account_class is AccountClass.LIABILITY:
                    liabilities += balances[row.id]
                else:
                    assets += balances[row.id]
        return NetWorth(as_of=as_of, assets=assets, liabilities=liabilities)

    def register(
        self,
        account_id: int,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> Register:
        """Return the transactions of an account with running balances.

        Args:
            account_id: The account.
            start: First day to include; `None` starts from the beginning.
            end: Last day to include; `None` includes every later transaction.

        Raises:
            NotFoundError: If the account does not exist.
            ValidationError: If `start` is after `end`.
        """
        start = v.optional_date(start, "start")
        end = v.optional_date(end, "end")
        v.date_range(start, end)
        with self._uow.session() as session:
            row = get_row(session, AccountRow, account_id, "account")
            opening = row.opening_date
            if start is None:
                starting = 0
                counted_later = opening is None or end is None or opening <= end
            else:
                starting = account_balances(
                    session, until=start, inclusive=False, account_ids=[row.id]
                )[row.id]
                counted_later = opening is not None and (
                    start <= opening and (end is None or opening <= end)
                )
            # The opening balance applies before any transaction of its day.
            if counted_later:
                starting += row.opening_balance
            ids = select(SplitRow.transaction_id).where(SplitRow.account_id == row.id)
            statement = select(TransactionRow).where(TransactionRow.id.in_(ids))
            if start is not None:
                statement = statement.where(TransactionRow.date >= start)
            if end is not None:
                statement = statement.where(TransactionRow.date <= end)
            statement = statement.order_by(TransactionRow.date, TransactionRow.id)
            running = starting
            entries = []
            for tx in session.scalars(statement):
                amount = sum(s.amount for s in tx.splits if s.account_id == row.id)
                running += amount
                entries.append(RegisterEntry(to_transaction(tx), amount, running))
            return Register(to_account(row), starting, tuple(entries))
