"""Debt endpoints: payoff forecasts, plans and loan payments."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from picciuli import UNSET, LumpSum, PayoffStrategy
from picciuli.limits import MAX_AMOUNT
from picciuli_api.deps import BookDep
from picciuli_api.schemas.accounts import AccountOut
from picciuli_api.schemas.base import Date, PathId, QueryDate, QueryId
from picciuli_api.schemas.debts import (
    DebtPlanIn,
    DebtPlanOut,
    DebtPlansOut,
    DebtStatusOut,
    LoanPaymentIn,
    LoanPaymentSplitOut,
)
from picciuli_api.schemas.transactions import TransactionOut

__all__ = ["router"]

router = APIRouter(prefix="/debts", tags=["debts"])


@router.get("")
def list_debts(book: BookDep, today: QueryDate = None) -> list[DebtStatusOut]:
    """List the open liabilities with debt terms and when they are paid off.

    Balances count the transactions up to `today` (default: the server date);
    payoff dates assume the minimum payment from the following month on.
    """
    return [
        DebtStatusOut(
            account=AccountOut.model_validate(status_.account),
            balance=status_.balance,
            owed=status_.owed,
            minimum_payment=status_.minimum_payment,
            next_due=status_.next_due,
            payoff=status_.payoff,
            interest_to_payoff=status_.interest_to_payoff,
            charges_to_payoff=status_.charges_to_payoff,
        )
        for status_ in book.debts.list(today=today)
    ]


@router.post("/plan")
def plan_payoff(book: BookDep, body: DebtPlanIn) -> DebtPlansOut:
    """Simulate paying off every debt with the snowball and avalanche strategies."""
    lump_sums = [LumpSum(item.date, item.amount) for item in body.lump_sums]

    def plan(strategy: PayoffStrategy) -> DebtPlanOut:
        return DebtPlanOut.model_validate(
            book.debts.plan(
                strategy=strategy,
                extra=body.extra,
                lump_sums=lump_sums,
                rollover=body.rollover,
                rollover_percent=body.rollover_percent,
                today=body.today,
            )
        )

    return DebtPlansOut(
        snowball=plan(PayoffStrategy.SNOWBALL),
        avalanche=plan(PayoffStrategy.AVALANCHE),
    )


@router.get("/{account_id:int}/payment-split")
def payment_split(
    book: BookDep,
    account_id: PathId,
    date: Date,
    amount: Annotated[int, Query(gt=0, le=MAX_AMOUNT)],
    exclude_transaction_id: QueryId = None,
) -> LoanPaymentSplitOut:
    """How a payment into a loan divides into interest, fixed charges and principal.

    Pass the payment being edited as `exclude_transaction_id`.
    """
    split = book.debts.loan_payment_split(
        account_id, date, amount, exclude_transaction_id=exclude_transaction_id
    )
    return LoanPaymentSplitOut.model_validate(split)


@router.post("/{account_id:int}/payments", status_code=status.HTTP_201_CREATED)
def record_payment(
    book: BookDep, account_id: PathId, body: LoanPaymentIn
) -> TransactionOut:
    """Record a payment into a loan, split into principal, interest and charges."""
    category = (
        body.interest_category_id
        if "interest_category_id" in body.model_fields_set
        else UNSET
    )
    transaction = book.debts.record_loan_payment(
        body.date,
        body.amount,
        loan_account_id=account_id,
        from_account_id=body.from_account_id,
        interest_category_id=category,
        description=body.description,
        notes=body.notes,
    )
    return TransactionOut.model_validate(transaction)
