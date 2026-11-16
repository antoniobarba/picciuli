"""Bodies of the transaction endpoints."""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from picciuli import AccountSplit, ExternalSplit, TradeKind, TransactionKind
from picciuli.limits import MAX_SPLITS

from .base import (
    Amount,
    Date,
    DecimalStr,
    Id,
    InputModel,
    Memo,
    OutputModel,
    PatchModel,
    PositiveAmount,
    SignedDecimal,
    Text,
)

__all__ = [
    "AccountSplitIn",
    "AccountSplitOut",
    "ExpenseCreate",
    "ExternalSplitIn",
    "ExternalSplitOut",
    "IncomeCreate",
    "SplitIn",
    "SplitOut",
    "TradeOut",
    "TransactionCreate",
    "TransactionOut",
    "TransactionUpdate",
    "TransferCreate",
]


class AccountSplitOut(OutputModel):
    """A split changing the balance of one of your accounts."""

    type: Literal["account"] = "account"
    account_id: int
    amount: int
    memo: str | None = None
    security_id: int | None = None
    quantity: DecimalStr | None = None


class ExternalSplitOut(OutputModel):
    """A split crossing the boundary of your accounts (income or expense)."""

    type: Literal["external"] = "external"
    amount: int
    category_id: int | None = None
    memo: str | None = None


SplitOut = Annotated[AccountSplitOut | ExternalSplitOut, Field(discriminator="type")]


class TradeOut(OutputModel):
    """The arguments of a purchase or sale of shares, as they were entered."""

    kind: TradeKind
    account_id: int
    security_id: int
    quantity: DecimalStr
    amount: int = Field(description="Cost of a purchase, or gross proceeds of a sale.")
    other_account_id: int | None = Field(
        description="Account paying or receiving the money; `null` for the "
        "investment account's own cash."
    )
    fee: int
    fee_category_id: int | None
    tax: int
    tax_category_id: int | None
    gain_category_id: int | None


def _tag_split(split: object) -> object:
    if isinstance(split, AccountSplit):
        return {"type": "account", **dataclasses.asdict(split)}
    if isinstance(split, ExternalSplit):
        return {"type": "external", **dataclasses.asdict(split)}
    return split


class TransactionOut(OutputModel):
    """A dated, balanced set of splits."""

    id: int
    date: dt.date
    description: str | None
    notes: str | None
    splits: list[SplitOut]
    kind: TransactionKind
    net_amount: int
    trade: TradeOut | None = Field(
        default=None,
        description="Set when the splits were built by a purchase or sale of "
        "shares; editing the splits directly removes it.",
    )
    schedule_id: int | None = Field(
        default=None,
        description="The recurring transaction that recorded it, if any.",
    )

    @field_validator("splits", mode="before")
    @classmethod
    def _tag_splits(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return [_tag_split(split) for split in value]
        return value


class AccountSplitIn(InputModel):
    """A split changing the balance of one of your accounts."""

    type: Literal["account"]
    account_id: Id
    amount: Amount
    memo: Memo | None = None
    security_id: Id | None = None
    quantity: SignedDecimal | None = None

    def to_model(self) -> AccountSplit:
        """Convert to the library type."""
        return AccountSplit(
            account_id=self.account_id,
            amount=self.amount,
            memo=self.memo,
            security_id=self.security_id,
            quantity=self.quantity,
        )


class ExternalSplitIn(InputModel):
    """A split crossing the boundary of your accounts (income or expense)."""

    type: Literal["external"]
    amount: Amount
    category_id: Id | None = None
    memo: Memo | None = None

    def to_model(self) -> ExternalSplit:
        """Convert to the library type."""
        return ExternalSplit(
            amount=self.amount, category_id=self.category_id, memo=self.memo
        )


SplitIn = Annotated[AccountSplitIn | ExternalSplitIn, Field(discriminator="type")]
SplitList = Annotated[list[SplitIn], Field(min_length=1, max_length=MAX_SPLITS)]


class TransactionCreate(InputModel):
    """A new transaction. Account splits must add up to the external splits."""

    date: Date
    splits: SplitList
    description: Text | None = None
    notes: Text | None = None


class TransactionUpdate(PatchModel):
    """Changes to a transaction. `splits` replaces every split."""

    _not_null = frozenset({"date", "splits"})

    date: Date | None = None
    splits: SplitList | None = None
    description: Text | None = None
    notes: Text | None = None

    def changes(self) -> dict[str, Any]:
        """Return the explicitly set fields, with splits converted."""
        changes = super().changes()
        if self.splits is not None:
            changes["splits"] = [split.to_model() for split in self.splits]
        return changes


class ExpenseCreate(InputModel):
    """Money spent from one account."""

    date: Date
    amount: PositiveAmount = Field(description="Positive amount spent, in minor units.")
    account_id: Id
    category_id: Id | None = None
    description: Text | None = None
    notes: Text | None = None


class IncomeCreate(InputModel):
    """Money received into one account."""

    date: Date
    amount: PositiveAmount = Field(description="Positive amount received.")
    account_id: Id
    category_id: Id | None = None
    description: Text | None = None
    notes: Text | None = None


class TransferCreate(InputModel):
    """Money moved between two of your accounts."""

    date: Date
    amount: PositiveAmount = Field(description="Positive amount moved.")
    from_account_id: Id
    to_account_id: Id
    description: Text | None = None
    notes: Text | None = None
