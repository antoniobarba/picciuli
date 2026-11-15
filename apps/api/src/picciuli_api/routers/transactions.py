"""Transaction endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query, status

from picciuli.limits import MAX_ID, MAX_NAME_LENGTH
from picciuli_api.deps import BookDep
from picciuli_api.schemas.base import Date, PathId, QueryDate, QueryId
from picciuli_api.schemas.transactions import (
    ExpenseCreate,
    IncomeCreate,
    TransactionCreate,
    TransactionOut,
    TransactionUpdate,
    TransferCreate,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("")
def list_transactions(
    book: BookDep,
    start: QueryDate = None,
    end: QueryDate = None,
    account_id: QueryId = None,
    category_id: QueryId = None,
    include_subcategories: bool = False,
    uncategorized: Annotated[
        bool, Query(description="Only transactions with uncategorized flows.")
    ] = False,
    text: Annotated[
        str | None,
        Query(
            max_length=MAX_NAME_LENGTH,
            description="Search in descriptions, notes and memos.",
        ),
    ] = None,
    newest_first: bool = False,
    limit: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
    offset: Annotated[int, Query(ge=0, le=MAX_ID)] = 0,
) -> list[TransactionOut]:
    """Search transactions. Every filter is optional; date ranges are inclusive."""
    found = book.transactions.list(
        start=start,
        end=end,
        account_id=account_id,
        category_id=category_id,
        include_subcategories=include_subcategories,
        uncategorized=uncategorized,
        text=text,
        newest_first=newest_first,
        limit=limit,
        offset=offset,
    )
    return [TransactionOut.model_validate(t) for t in found]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_transaction(book: BookDep, body: TransactionCreate) -> TransactionOut:
    """Record a transaction with explicit splits."""
    transaction = book.transactions.create(
        body.date,
        [split.to_model() for split in body.splits],
        description=body.description,
        notes=body.notes,
    )
    return TransactionOut.model_validate(transaction)


@router.get("/dates")
def dates_with_transactions(
    book: BookDep, start: Date, end: Date, account_id: QueryId = None
) -> list[dt.date]:
    """Days between `start` and `end` with at least one transaction."""
    return book.transactions.dates_with_transactions(start, end, account_id=account_id)


@router.post("/expense", status_code=status.HTTP_201_CREATED)
def record_expense(book: BookDep, body: ExpenseCreate) -> TransactionOut:
    """Record money spent from one account."""
    transaction = book.transactions.record_expense(
        body.date,
        body.amount,
        account_id=body.account_id,
        category_id=body.category_id,
        description=body.description,
        notes=body.notes,
    )
    return TransactionOut.model_validate(transaction)


@router.post("/income", status_code=status.HTTP_201_CREATED)
def record_income(book: BookDep, body: IncomeCreate) -> TransactionOut:
    """Record money received into one account."""
    transaction = book.transactions.record_income(
        body.date,
        body.amount,
        account_id=body.account_id,
        category_id=body.category_id,
        description=body.description,
        notes=body.notes,
    )
    return TransactionOut.model_validate(transaction)


@router.post("/transfer", status_code=status.HTTP_201_CREATED)
def record_transfer(book: BookDep, body: TransferCreate) -> TransactionOut:
    """Record money moved between two of your accounts."""
    transaction = book.transactions.record_transfer(
        body.date,
        body.amount,
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        description=body.description,
        notes=body.notes,
    )
    return TransactionOut.model_validate(transaction)


@router.get("/{transaction_id:int}")
def get_transaction(book: BookDep, transaction_id: PathId) -> TransactionOut:
    """Get one transaction."""
    return TransactionOut.model_validate(book.transactions.get(transaction_id))


@router.patch("/{transaction_id:int}")
def update_transaction(
    book: BookDep, transaction_id: PathId, body: TransactionUpdate
) -> TransactionOut:
    """Change a transaction. A `splits` list replaces every split."""
    transaction = book.transactions.update(transaction_id, **body.changes())
    return TransactionOut.model_validate(transaction)


@router.delete("/{transaction_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(book: BookDep, transaction_id: PathId) -> None:
    """Delete a transaction."""
    book.transactions.delete(transaction_id)
