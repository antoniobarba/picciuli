"""Transactions: balanced sets of account and external splits."""

from __future__ import annotations

import builtins
import datetime as dt
from collections.abc import Iterable, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._db.queries import check_holdings, get_row, to_split, to_transaction
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import (
    AccountRow,
    CategoryRow,
    SecurityRow,
    SplitRow,
    TransactionRow,
)
from picciuli._decimal import to_decimal, to_scaled
from picciuli.errors import ConflictError, ValidationError
from picciuli.model import (
    UNSET,
    AccountSplit,
    AccountType,
    ExternalSplit,
    Split,
    Transaction,
    Unset,
)

__all__ = ["TransactionService"]


def _security_pairs(rows: Iterable[SplitRow]) -> set[tuple[int, int]]:
    return {
        (row.account_id, row.security_id)
        for row in rows
        if row.account_id is not None and row.security_id is not None
    }


def _validated_splits(
    session: Session, day: dt.date, splits: object
) -> builtins.list[SplitRow]:
    if isinstance(splits, (str, bytes)) or not isinstance(splits, Sequence):
        raise ValidationError("splits must be a sequence of AccountSplit/ExternalSplit")
    if not splits:
        raise ValidationError("a transaction needs at least one split")
    rows: list[SplitRow] = []
    account_total = external_total = 0
    for position, split in enumerate(splits, start=1):
        if not isinstance(split, (AccountSplit, ExternalSplit)):
            raise ValidationError(
                f"split {position} must be an AccountSplit or an ExternalSplit"
            )
        amount = v.integer(split.amount, f"split {position} amount")
        moves_shares = isinstance(split, AccountSplit) and (
            split.security_id is not None or split.quantity is not None
        )
        if amount == 0 and not moves_shares:
            raise ValidationError(f"split {position} amount cannot be zero")
        memo = v.optional_text(split.memo, f"split {position} memo")
        if isinstance(split, AccountSplit):
            account_id = v.identifier(split.account_id, f"split {position} account id")
            account = get_row(session, AccountRow, account_id, "account")
            if account.closed_on is not None:
                raise ConflictError(f"account {account.name!r} is closed")
            if account.opening_date is not None and day < account.opening_date:
                raise ValidationError(
                    f"account {account.name!r} opens on "
                    f"{account.opening_date.isoformat()}, after the transaction date"
                )
            security_id = quantity = None
            if moves_shares:
                if split.security_id is None or split.quantity is None:
                    raise ValidationError(
                        f"split {position} needs both a security and a quantity"
                    )
                if account.type != AccountType.INVESTMENT.value:
                    raise ValidationError(
                        f"account {account.name!r} is not an investment account "
                        "and cannot hold securities"
                    )
                security_id = v.identifier(
                    split.security_id, f"split {position} security id"
                )
                get_row(session, SecurityRow, security_id, "security")
                shares = to_decimal(split.quantity, f"split {position} quantity")
                if shares == 0:
                    raise ValidationError(f"split {position} quantity cannot be zero")
                quantity = to_scaled(shares)
            account_total += amount
            rows.append(
                SplitRow(
                    position=position,
                    account_id=account_id,
                    amount=amount,
                    memo=memo,
                    security_id=security_id,
                    quantity=quantity,
                )
            )
        else:
            category_id = split.category_id
            if category_id is not None:
                category_id = v.identifier(category_id, f"split {position} category id")
                get_row(session, CategoryRow, category_id, "category")
            external_total += amount
            rows.append(
                SplitRow(
                    position=position, category_id=category_id, amount=amount, memo=memo
                )
            )
    if not any(row.account_id is not None for row in rows):
        raise ValidationError("a transaction needs at least one account split")
    if account_total != external_total:
        raise ValidationError(
            f"unbalanced splits: account splits total {account_total}, "
            f"external splits total {external_total}"
        )
    return rows


def _ensure_editable(session: Session, row: TransactionRow) -> None:
    for split in row.splits:
        if split.account_id is None:
            continue
        account = get_row(session, AccountRow, split.account_id, "account")
        if account.closed_on is not None:
            raise ConflictError(
                f"the transaction involves the closed account {account.name!r}"
            )


class TransactionService:
    """Record, edit, delete and search transactions.

    Obtain it as [`Book.transactions`][picciuli.Book.transactions].

    A transaction is a dated list of splits. Account splits change account
    balances; external splits are money entering (positive) or leaving
    (negative) your accounts, optionally categorized. The sum of the account
    splits must equal the sum of the external splits; a transfer simply has no
    external splits. See [`Transaction`][picciuli.model.Transaction] for examples.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(
        self,
        date: dt.date,
        splits: Sequence[Split],
        *,
        description: str | None = None,
        notes: str | None = None,
    ) -> Transaction:
        """Record a transaction.

        Args:
            date: Day of the transaction.
            splits: At least one [`AccountSplit`][picciuli.model.AccountSplit]
                plus any number of [`ExternalSplit`][picciuli.model.ExternalSplit]
                objects, with non-zero amounts that balance.
            description: Short description, for example a payee.
            notes: Free text.

        Returns:
            The stored transaction.

        Raises:
            ValidationError: If an argument is invalid or the splits do not
                balance, or the date is before an account's opening date.
            NotFoundError: If an account or category does not exist.
            ConflictError: If an account is closed.
        """
        day = v.date(date, "date")
        description = v.optional_text(description, "description")
        notes = v.optional_text(notes, "notes")
        with self._uow.session() as session:
            row = TransactionRow(
                date=day,
                description=description,
                notes=notes,
                splits=_validated_splits(session, day, splits),
            )
            session.add(row)
            check_holdings(session, _security_pairs(row.splits))
            session.flush()
            return to_transaction(row)

    def get(self, transaction_id: int) -> Transaction:
        """Return a transaction.

        Raises:
            NotFoundError: If the transaction does not exist.
        """
        with self._uow.session() as session:
            return to_transaction(
                get_row(session, TransactionRow, transaction_id, "transaction")
            )

    def update(
        self,
        transaction_id: int,
        *,
        date: dt.date | Unset = UNSET,
        splits: Sequence[Split] | Unset = UNSET,
        description: str | None | Unset = UNSET,
        notes: str | None | Unset = UNSET,
    ) -> Transaction:
        """Change a transaction; arguments left `UNSET` are not modified.

        Passing `splits` replaces all existing splits. The splits (old or new) are
        validated again against the new date.

        Raises:
            NotFoundError: If the transaction, an account or a category does not
                exist.
            ValidationError: If an argument is invalid or the splits do not
                balance.
            ConflictError: If the transaction currently involves a closed
                account, or the new splits use one.
        """
        with self._uow.session() as session:
            row = get_row(session, TransactionRow, transaction_id, "transaction")
            _ensure_editable(session, row)
            day = row.date if isinstance(date, Unset) else v.date(date, "date")
            affected = _security_pairs(row.splits)
            if isinstance(splits, Unset):
                current = [to_split(s) for s in row.splits]
                new_rows = _validated_splits(session, day, current)
            else:
                new_rows = _validated_splits(session, day, splits)
            row.date = day
            if not isinstance(description, Unset):
                row.description = v.optional_text(description, "description")
            if not isinstance(notes, Unset):
                row.notes = v.optional_text(notes, "notes")
            if not isinstance(splits, Unset):
                row.splits.clear()
                session.flush()
                row.splits.extend(new_rows)
            check_holdings(session, affected | _security_pairs(new_rows))
            session.flush()
            return to_transaction(row)

    def delete(self, transaction_id: int) -> None:
        """Delete a transaction.

        Raises:
            NotFoundError: If the transaction does not exist.
            ConflictError: If the transaction involves a closed account.
            ValidationError: If removing it would make a share quantity
                negative (a later sale needs the shares it bought).
        """
        with self._uow.session() as session:
            row = get_row(session, TransactionRow, transaction_id, "transaction")
            _ensure_editable(session, row)
            affected = _security_pairs(row.splits)
            session.delete(row)
            check_holdings(session, affected)

    def list(
        self,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
        account_id: int | None = None,
        category_id: int | None = None,
        include_subcategories: bool = False,
        uncategorized: bool = False,
        text: str | None = None,
        newest_first: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> builtins.list[Transaction]:
        """Search transactions; all filters are combined.

        Args:
            start: First day to include.
            end: Last day to include.
            account_id: Only transactions with a split on this account.
            category_id: Only transactions with an external split in this
                category.
            include_subcategories: With `category_id`, also match its
                subcategories.
            uncategorized: Only transactions with an uncategorized external
                split. Cannot be combined with `category_id`.
            text: Case-insensitive substring of the description, notes or a
                split memo.
            newest_first: Sort by descending date instead of ascending.
            limit: Maximum number of results.
            offset: Number of results to skip (for paging).

        Returns:
            Matching transactions ordered by date, then by creation order.

        Raises:
            ValidationError: If an argument is invalid.
        """
        start = v.optional_date(start, "start")
        end = v.optional_date(end, "end")
        v.date_range(start, end)
        if category_id is not None and uncategorized:
            raise ValidationError("category_id and uncategorized are exclusive")
        statement = select(TransactionRow)
        if start is not None:
            statement = statement.where(TransactionRow.date >= start)
        if end is not None:
            statement = statement.where(TransactionRow.date <= end)
        if account_id is not None:
            v.identifier(account_id, "account id")
            statement = statement.where(
                TransactionRow.id.in_(
                    select(SplitRow.transaction_id).where(
                        SplitRow.account_id == account_id
                    )
                )
            )
        if category_id is not None:
            v.identifier(category_id, "category id")
            matches = CategoryRow.id == category_id
            if include_subcategories:
                matches = or_(matches, CategoryRow.parent_id == category_id)
            categories = select(CategoryRow.id).where(matches)
            statement = statement.where(
                TransactionRow.id.in_(
                    select(SplitRow.transaction_id).where(
                        SplitRow.category_id.in_(categories)
                    )
                )
            )
        if uncategorized:
            statement = statement.where(
                TransactionRow.id.in_(
                    select(SplitRow.transaction_id).where(
                        and_(
                            SplitRow.account_id.is_(None),
                            SplitRow.category_id.is_(None),
                        )
                    )
                )
            )
        if text is not None:
            if not isinstance(text, str):
                raise ValidationError("text must be a string")
            needle = text.strip().lower()
            if needle:
                statement = statement.where(
                    or_(
                        TransactionRow.description.icontains(needle, autoescape=True),
                        TransactionRow.notes.icontains(needle, autoescape=True),
                        TransactionRow.id.in_(
                            select(SplitRow.transaction_id).where(
                                SplitRow.memo.icontains(needle, autoescape=True)
                            )
                        ),
                    )
                )
        if newest_first:
            statement = statement.order_by(
                TransactionRow.date.desc(), TransactionRow.id.desc()
            )
        else:
            statement = statement.order_by(TransactionRow.date, TransactionRow.id)
        if limit is not None:
            statement = statement.limit(v.integer(limit, "limit"))
        offset = v.integer(offset, "offset")
        if offset < 0 or (limit is not None and limit < 0):
            raise ValidationError("limit and offset cannot be negative")
        if offset:
            statement = statement.offset(offset)
        with self._uow.session() as session:
            return [to_transaction(row) for row in session.scalars(statement)]

    def dates_with_transactions(
        self, start: dt.date, end: dt.date, *, account_id: int | None = None
    ) -> builtins.list[dt.date]:
        """Return the distinct days with at least one transaction, ascending.

        Useful to mark days in a calendar view.

        Args:
            start: First day to include.
            end: Last day to include.
            account_id: Only consider transactions involving this account.

        Raises:
            ValidationError: If the range is invalid.
        """
        start = v.date(start, "start")
        end = v.date(end, "end")
        v.date_range(start, end)
        statement = (
            select(TransactionRow.date)
            .distinct()
            .where(TransactionRow.date >= start, TransactionRow.date <= end)
            .order_by(TransactionRow.date)
        )
        if account_id is not None:
            v.identifier(account_id, "account id")
            statement = statement.where(
                TransactionRow.id.in_(
                    select(SplitRow.transaction_id).where(
                        SplitRow.account_id == account_id
                    )
                )
            )
        with self._uow.session() as session:
            return builtins.list(session.scalars(statement))

    def record_expense(
        self,
        date: dt.date,
        amount: int,
        *,
        account_id: int,
        category_id: int | None = None,
        description: str | None = None,
        notes: str | None = None,
    ) -> Transaction:
        """Record money leaving an account to the outside world.

        Args:
            date: Day of the expense.
            amount: Positive amount spent, in minor units.
            account_id: Account the money leaves (for example a checking
                account or a credit card).
            category_id: Category of the expense, or `None` for uncategorized.
            description: Short description.
            notes: Free text.

        Raises:
            ValidationError: If `amount` is not positive or another argument is
                invalid.
            NotFoundError: If the account or category does not exist.
            ConflictError: If the account is closed.
        """
        amount = v.positive_integer(amount, "amount")
        return self.create(
            date,
            [
                AccountSplit(account_id, -amount),
                ExternalSplit(-amount, category_id),
            ],
            description=description,
            notes=notes,
        )

    def record_income(
        self,
        date: dt.date,
        amount: int,
        *,
        account_id: int,
        category_id: int | None = None,
        description: str | None = None,
        notes: str | None = None,
    ) -> Transaction:
        """Record money entering an account from the outside world.

        Args:
            date: Day of the income.
            amount: Positive amount received, in minor units.
            account_id: Account receiving the money.
            category_id: Category of the income, or `None` for uncategorized.
            description: Short description.
            notes: Free text.

        Raises:
            ValidationError: If `amount` is not positive or another argument is
                invalid.
            NotFoundError: If the account or category does not exist.
            ConflictError: If the account is closed.
        """
        amount = v.positive_integer(amount, "amount")
        return self.create(
            date,
            [AccountSplit(account_id, amount), ExternalSplit(amount, category_id)],
            description=description,
            notes=notes,
        )

    def record_transfer(
        self,
        date: dt.date,
        amount: int,
        *,
        from_account_id: int,
        to_account_id: int,
        description: str | None = None,
        notes: str | None = None,
    ) -> Transaction:
        """Move money between two of your accounts.

        Paying a credit card bill, depositing into savings, receiving a loan
        disbursement and repaying principal are all transfers.

        Args:
            date: Day of the transfer.
            amount: Positive amount moved, in minor units.
            from_account_id: Account the money leaves.
            to_account_id: Account the money enters.
            description: Short description.
            notes: Free text.

        Raises:
            ValidationError: If `amount` is not positive, both accounts are the
                same, or another argument is invalid.
            NotFoundError: If an account does not exist.
            ConflictError: If an account is closed.
        """
        amount = v.positive_integer(amount, "amount")
        if from_account_id == to_account_id:
            raise ValidationError("cannot transfer to the same account")
        return self.create(
            date,
            [
                AccountSplit(from_account_id, -amount),
                AccountSplit(to_account_id, amount),
            ],
            description=description,
            notes=notes,
        )
