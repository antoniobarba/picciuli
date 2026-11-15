"""Bodies of the transaction endpoints."""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from picciuli import AccountSplit, ExternalSplit, TransactionKind

from .base import DecimalStr, InputModel, OutputModel, PatchModel

__all__ = [
    "AccountSplitIn",
    "AccountSplitOut",
    "ExpenseCreate",
    "ExternalSplitIn",
    "ExternalSplitOut",
    "IncomeCreate",
    "SplitIn",
    "SplitOut",
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

    @field_validator("splits", mode="before")
    @classmethod
    def _tag_splits(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return [_tag_split(split) for split in value]
        return value


class AccountSplitIn(InputModel):
    """A split changing the balance of one of your accounts."""

    type: Literal["account"]
    account_id: int
    amount: int
    memo: str | None = None
    security_id: int | None = None
    quantity: Decimal | None = None

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
    amount: int
    category_id: int | None = None
    memo: str | None = None

    def to_model(self) -> ExternalSplit:
        """Convert to the library type."""
        return ExternalSplit(
            amount=self.amount, category_id=self.category_id, memo=self.memo
        )


SplitIn = Annotated[AccountSplitIn | ExternalSplitIn, Field(discriminator="type")]


class TransactionCreate(InputModel):
    """A new transaction. Account splits must add up to the external splits."""

    date: dt.date
    splits: list[SplitIn]
    description: str | None = None
    notes: str | None = None


class TransactionUpdate(PatchModel):
    """Changes to a transaction. `splits` replaces every split."""

    date: dt.date | None = None
    splits: list[SplitIn] | None = None
    description: str | None = None
    notes: str | None = None

    def changes(self) -> dict[str, Any]:
        """Return the explicitly set fields, with splits converted."""
        changes = super().changes()
        if self.splits is not None:
            changes["splits"] = [split.to_model() for split in self.splits]
        return changes


class ExpenseCreate(InputModel):
    """Money spent from one account."""

    date: dt.date
    amount: int = Field(gt=0, description="Positive amount spent, in minor units.")
    account_id: int
    category_id: int | None = None
    description: str | None = None
    notes: str | None = None


class IncomeCreate(InputModel):
    """Money received into one account."""

    date: dt.date
    amount: int = Field(gt=0, description="Positive amount received.")
    account_id: int
    category_id: int | None = None
    description: str | None = None
    notes: str | None = None


class TransferCreate(InputModel):
    """Money moved between two of your accounts."""

    date: dt.date
    amount: int = Field(gt=0, description="Positive amount moved.")
    from_account_id: int
    to_account_id: int
    description: str | None = None
    notes: str | None = None
