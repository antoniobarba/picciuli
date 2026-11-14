"""SQLAlchemy table definitions (private).

ORM rows never leave the library: services convert them to the immutable
dataclasses of `picciuli.model` before returning.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from picciuli.model import AccountType

_ACCOUNT_TYPES = ", ".join(f"'{t.value}'" for t in AccountType)


class Base(DeclarativeBase):
    pass


class MetaRow(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)


class AccountRow(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(f"type IN ({_ACCOUNT_TYPES})", name="ck_account_type"),
        CheckConstraint(
            "closed_on IS NULL OR opening_date IS NULL OR closed_on >= opening_date",
            name="ck_account_dates",
        ),
        CheckConstraint("position >= 1", name="ck_account_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(collation="NOCASE"), unique=True)
    type: Mapped[str] = mapped_column(String)
    opening_balance: Mapped[int] = mapped_column(Integer)
    opening_date: Mapped[dt.date | None] = mapped_column(Date)
    goal: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    closed_on: Mapped[dt.date | None] = mapped_column(Date)


class CategoryRow(Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("length(symbol) BETWEEN 1 AND 12", name="ck_category_symbol"),
        CheckConstraint(
            "parent_id IS NULL OR parent_id != id", name="ck_category_parent"
        ),
        CheckConstraint("position >= 1", name="ck_category_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(collation="NOCASE"), unique=True)
    symbol: Mapped[str] = mapped_column(String(12))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(Integer)


class PeriodRow(Base):
    __tablename__ = "periods"
    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR start_date <= end_date", name="ck_period_dates"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    start_date: Mapped[dt.date] = mapped_column(Date, index=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date)


class BudgetRow(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_budget_amount"),
        UniqueConstraint("category_id", "period_id", name="uq_budget_category_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id", ondelete="CASCADE"))
    amount: Mapped[int] = mapped_column(Integer)


class TransactionRow(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    description: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    splits: Mapped[list[SplitRow]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="SplitRow.position",
        lazy="selectin",
    )


class SplitRow(Base):
    __tablename__ = "splits"
    __table_args__ = (
        CheckConstraint("amount != 0", name="ck_split_amount"),
        CheckConstraint(
            "account_id IS NULL OR category_id IS NULL", name="ck_split_kind"
        ),
        Index("ix_splits_account", "account_id"),
        Index("ix_splits_category", "category_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT")
    )
    amount: Mapped[int] = mapped_column(Integer)
    memo: Mapped[str | None] = mapped_column(String)
    transaction: Mapped[TransactionRow] = relationship(back_populates="splits")
