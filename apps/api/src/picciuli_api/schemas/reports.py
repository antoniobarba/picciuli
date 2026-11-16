"""Bodies of the report endpoints."""

from __future__ import annotations

import datetime as dt

from .base import OutputModel

__all__ = ["HistoryBalanceOut", "HistoryFlowOut", "HistoryPointOut"]


class HistoryFlowOut(OutputModel):
    """Net external flow of one category, without its subcategories."""

    category_id: int | None
    """The category; `null` for the splits without one."""
    amount: int


class HistoryBalanceOut(OutputModel):
    """An account balance at the end of a history point."""

    account_id: int
    balance: int
    """Ledger balance."""
    value: int
    """Market value: shares valued with the prices known then (else at cost)."""


class HistoryPointOut(OutputModel):
    """Cash flows during a month or period and balances at its end."""

    start: dt.date
    end: dt.date
    """Last day counted: the current day for a month or period still running."""
    period_id: int | None
    """The period, for points by period; `null` for months."""
    partial: bool
    """Whether the month or period continues after `end`."""
    income: int
    expenses: int
    flows: list[HistoryFlowOut]
    """Non-zero category flows in display order, uncategorized last."""
    balances: list[HistoryBalanceOut]
    """Accounts with a non-zero balance or value, in display order."""
    assets: int
    liabilities: int
    net_worth: int
    """Assets plus liabilities, at market value."""
