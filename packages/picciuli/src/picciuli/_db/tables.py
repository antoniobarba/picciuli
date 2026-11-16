"""SQLAlchemy table definitions (private).

ORM rows never leave the library: services convert them to the immutable
dataclasses of `picciuli.model` before returning.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
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

from picciuli.model import AccountType, ScheduleFrequency, ScheduleMode, SecurityKind

_ACCOUNT_TYPES = ", ".join(f"'{t.value}'" for t in AccountType)
_SECURITY_KINDS = ", ".join(f"'{k.value}'" for k in SecurityKind)
_FREQUENCIES = ", ".join(f"'{f.value}'" for f in ScheduleFrequency)
_SCHEDULE_MODES = ", ".join(f"'{m.value}'" for m in ScheduleMode)


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
    # Added by schema version 4 with ALTER TABLE, so it must stay the last
    # column. It has no foreign key, which SQLite cannot add to an existing
    # table in the same form as a new one: deleting a schedule clears it.
    schedule_id: Mapped[int | None] = mapped_column(Integer, index=True)
    splits: Mapped[list[SplitRow]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="SplitRow.position",
        lazy="selectin",
    )
    trade: Mapped[TradeRow | None] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class TradeRow(Base):
    """The arguments of a purchase or sale, kept next to the splits they built."""

    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("kind IN ('buy', 'sell')", name="ck_trade_kind"),
        CheckConstraint("quantity > 0", name="ck_trade_quantity"),
        CheckConstraint("amount > 0", name="ck_trade_amount"),
        CheckConstraint("fee >= 0 AND tax >= 0", name="ck_trade_fees"),
        CheckConstraint(
            "kind = 'sell' OR (tax = 0 AND tax_category_id IS NULL "
            "AND gain_category_id IS NULL)",
            name="ck_trade_buy",
        ),
    )

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT")
    )
    # Number of shares scaled by 10**8 (see picciuli._decimal.SCALE).
    quantity: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    other_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    fee: Mapped[int] = mapped_column(Integer)
    fee_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT")
    )
    tax: Mapped[int] = mapped_column(Integer)
    tax_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT")
    )
    gain_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT")
    )


class SplitRow(Base):
    __tablename__ = "splits"
    __table_args__ = (
        CheckConstraint(
            "amount != 0 OR security_id IS NOT NULL", name="ck_split_amount"
        ),
        CheckConstraint(
            "account_id IS NULL OR category_id IS NULL", name="ck_split_kind"
        ),
        CheckConstraint(
            "(security_id IS NULL AND quantity IS NULL) OR "
            "(security_id IS NOT NULL AND quantity IS NOT NULL "
            "AND quantity != 0 AND account_id IS NOT NULL)",
            name="ck_split_security",
        ),
        Index("ix_splits_account", "account_id"),
        Index("ix_splits_category", "category_id"),
        Index("ix_splits_security", "security_id"),
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
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT")
    )
    # Number of shares scaled by 10**8 (see picciuli._decimal.SCALE).
    quantity: Mapped[int | None] = mapped_column(Integer)
    transaction: Mapped[TransactionRow] = relationship(back_populates="splits")


class ScheduleRow(Base):
    """A recurring transaction: a template of splits and when to repeat it."""

    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint(f"frequency IN ({_FREQUENCIES})", name="ck_schedule_frequency"),
        CheckConstraint("every >= 1", name="ck_schedule_every"),
        CheckConstraint(
            "(frequency IN ('monthly', 'yearly') AND day_of_month BETWEEN 1 AND 31) "
            "OR (frequency IN ('daily', 'weekly') AND day_of_month IS NULL)",
            name="ck_schedule_day_of_month",
        ),
        CheckConstraint(
            "remaining IS NULL OR remaining >= 0", name="ck_schedule_remaining"
        ),
        CheckConstraint(f"mode IN ({_SCHEDULE_MODES})", name="ck_schedule_mode"),
        CheckConstraint("paused IN (0, 1)", name="ck_schedule_paused"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[str] = mapped_column(String)
    every: Mapped[int] = mapped_column(Integer)
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    # Day of the next occurrence; NULL once the schedule has finished.
    next_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    # Occurrences left, including `next_date`; NULL for no limit.
    remaining: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String)
    paused: Mapped[bool] = mapped_column(Boolean)
    last_error: Mapped[str | None] = mapped_column(Text)
    splits: Mapped[list[ScheduleSplitRow]] = relationship(
        cascade="all, delete-orphan",
        order_by="ScheduleSplitRow.position",
        lazy="selectin",
    )


class ScheduleSplitRow(Base):
    __tablename__ = "schedule_splits"
    __table_args__ = (
        CheckConstraint("amount != 0", name="ck_schedule_split_amount"),
        CheckConstraint(
            "account_id IS NULL OR category_id IS NULL", name="ck_schedule_split_kind"
        ),
        Index("ix_schedule_splits_account", "account_id"),
        Index("ix_schedule_splits_category", "category_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), index=True
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


class SecurityRow(Base):
    __tablename__ = "securities"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_SECURITY_KINDS})", name="ck_security_kind"),
        CheckConstraint("length(currency) = 3", name="ck_security_currency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(collation="NOCASE"), unique=True)
    symbol: Mapped[str | None] = mapped_column(String)
    isin: Mapped[str | None] = mapped_column(String(12), unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    kind: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)


class PriceRow(Base):
    __tablename__ = "prices"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_price_positive"),
        UniqueConstraint("security_id", "date", name="uq_price_security_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE")
    )
    date: Mapped[dt.date] = mapped_column(Date)
    # Price scaled by 10**8.
    price: Mapped[int] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(String)


class ExchangeRateRow(Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        CheckConstraint("rate > 0", name="ck_exchange_rate_positive"),
        CheckConstraint("length(currency) = 3", name="ck_exchange_rate_currency"),
        UniqueConstraint("currency", "date", name="uq_exchange_rate_currency_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    date: Mapped[dt.date] = mapped_column(Date)
    # Rate scaled by 10**8.
    rate: Mapped[int] = mapped_column(Integer)
