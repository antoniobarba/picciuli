"""Account endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from picciuli_api.deps import BookDep
from picciuli_api.schemas.accounts import (
    AccountBalanceOut,
    AccountCreate,
    AccountMove,
    AccountOut,
    AccountUpdate,
    BalanceOut,
    CloseAccount,
    NetWorthOut,
)
from picciuli_api.schemas.base import PathId, QueryDate
from picciuli_api.schemas.misc import RegisterOut

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("")
def list_accounts(book: BookDep, include_closed: bool = True) -> list[AccountOut]:
    """List the accounts in display order."""
    accounts = book.accounts.list(include_closed=include_closed)
    return [AccountOut.model_validate(a) for a in accounts]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_account(book: BookDep, body: AccountCreate) -> AccountOut:
    """Create an account."""
    account = book.accounts.create(
        body.name,
        body.type,
        opening_balance=body.opening_balance,
        opening_date=body.opening_date,
        goal=body.goal,
        notes=body.notes,
    )
    return AccountOut.model_validate(account)


@router.get("/balances")
def list_balances(
    book: BookDep, as_of: QueryDate = None, include_closed: bool = False
) -> list[AccountBalanceOut]:
    """List every account with its balance on a day (default: all transactions)."""
    balances = book.accounts.balances(as_of=as_of, include_closed=include_closed)
    return [AccountBalanceOut.model_validate(b) for b in balances]


@router.get("/net-worth")
def net_worth(book: BookDep, as_of: QueryDate = None) -> NetWorthOut:
    """Total assets and liabilities, at ledger value (see investments for market)."""
    return NetWorthOut.model_validate(book.accounts.net_worth(as_of=as_of))


@router.get("/{account_id:int}")
def get_account(book: BookDep, account_id: PathId) -> AccountOut:
    """Get one account."""
    return AccountOut.model_validate(book.accounts.get(account_id))


@router.patch("/{account_id:int}")
def update_account(
    book: BookDep, account_id: PathId, body: AccountUpdate
) -> AccountOut:
    """Change some fields of an account."""
    account = book.accounts.update(account_id, **body.changes())
    return AccountOut.model_validate(account)


@router.delete("/{account_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(book: BookDep, account_id: PathId) -> None:
    """Delete an account that was never used."""
    book.accounts.delete(account_id)


@router.post("/{account_id:int}/move")
def move_account(book: BookDep, account_id: PathId, body: AccountMove) -> AccountOut:
    """Move an account to another display position."""
    return AccountOut.model_validate(book.accounts.move(account_id, body.position))


@router.post("/{account_id:int}/close")
def close_account(
    book: BookDep, account_id: PathId, body: CloseAccount | None = None
) -> AccountOut:
    """Close an account with a zero balance."""
    on = body.on if body is not None else None
    return AccountOut.model_validate(book.accounts.close(account_id, on=on))


@router.post("/{account_id:int}/reopen")
def reopen_account(book: BookDep, account_id: PathId) -> AccountOut:
    """Reopen a closed account."""
    return AccountOut.model_validate(book.accounts.reopen(account_id))


@router.get("/{account_id:int}/balance")
def account_balance(
    book: BookDep, account_id: PathId, as_of: QueryDate = None
) -> BalanceOut:
    """Balance of one account on a day (default: all transactions)."""
    balance = book.accounts.balance(account_id, as_of=as_of)
    return BalanceOut(account_id=account_id, as_of=as_of, balance=balance)


@router.get("/{account_id:int}/register")
def account_register(
    book: BookDep,
    account_id: PathId,
    start: QueryDate = None,
    end: QueryDate = None,
) -> RegisterOut:
    """The transactions of one account with running balances."""
    register = book.accounts.register(account_id, start=start, end=end)
    return RegisterOut.model_validate(register)
