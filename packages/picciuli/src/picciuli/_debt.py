"""Interest, minimum payments and payoff simulations of debts (private).

Everything here is pure arithmetic on integers in minor units and `Decimal`
percentages; nothing reads the database. Interest is rounded half-even to
whole minor units.
"""

from __future__ import annotations

import datetime as dt
import decimal
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from picciuli import _calendar
from picciuli.model import PayoffStrategy, Rollover

MAX_PLAN_MONTHS: Final = 1200
"""Longest simulated plan: 100 years."""

_RUNAWAY: Final = 10**18
"""Total owed past which a plan stops: the debts grow instead of shrinking."""


def _round(value: Decimal) -> int:
    with decimal.localcontext() as context:
        context.prec = 80
        return int(value.to_integral_value(rounding=decimal.ROUND_HALF_EVEN))


def monthly_interest(owed: int, annual_rate: Decimal) -> int:
    """One month of interest on `owed` at `annual_rate` percent (loans)."""
    if owed <= 0 or annual_rate <= 0:
        return 0
    with decimal.localcontext() as context:
        context.prec = 80
        return _round(Decimal(owed) * annual_rate / 1200)


def daily_interest(owed_by_day: Iterable[int], annual_rate: Decimal) -> int:
    """Interest on a sequence of daily balances owed (credit cards).

    Equal to the average daily balance times `annual_rate / 365` times the
    number of days, computed exactly before rounding once.
    """
    if annual_rate <= 0:
        return 0
    total = sum(max(0, owed) for owed in owed_by_day)
    if total == 0:
        return 0
    with decimal.localcontext() as context:
        context.prec = 80
        return _round(Decimal(total) * annual_rate / 36500)


def minimum_payment(
    owed: int,
    *,
    card: bool,
    payment: int | None,
    percent: Decimal | None,
    charges: int = 0,
) -> int | None:
    """What is due on `owed`, never more than `owed` plus `charges`; `None` if unknown.

    A loan owes its fixed `payment`, which includes its fixed `charges`. A
    credit card owes `percent` of the balance, at least `payment` (the floor).
    """
    if owed <= 0:
        return 0
    if not card:
        return (
            None if payment is None else min(owed, max(0, payment - charges)) + charges
        )
    candidates = []
    if percent is not None:
        with decimal.localcontext() as context:
            context.prec = 80
            candidates.append(_round(Decimal(owed) * percent / 100))
    if payment is not None:
        candidates.append(payment)
    if not candidates:
        return None
    return min(owed, max(candidates))


def on_or_after(day: dt.date, day_of_month: int) -> dt.date:
    """First day on or after `day` that falls on `day_of_month`.

    Shorter months use their last day, as schedules do.
    """
    this_month = _calendar.add_months(day, 0, day_of_month)
    if this_month is not None and this_month >= day:
        return this_month
    following = _calendar.add_months(day, 1, day_of_month)
    if following is None:
        raise OverflowError("date out of range")
    return following


def before(day: dt.date, day_of_month: int) -> dt.date:
    """Last day strictly before `day` that falls on `day_of_month`."""
    this_month = _calendar.add_months(day, 0, day_of_month)
    if this_month is not None and this_month < day:
        return this_month
    previous = _calendar.add_months(day, -1, day_of_month)
    if previous is None:
        raise OverflowError("date out of range")
    return previous


@dataclass(frozen=True, slots=True)
class PlanDebt:
    """One debt entering a payoff simulation."""

    id: int
    owed: int
    annual_rate: Decimal
    card: bool
    payment: int | None
    percent: Decimal | None
    charges: int = 0
    """Fixed charges included in every payment of a loan."""

    def fee(self, owed: int) -> int:
        """The fixed charges paid in a month in which `owed` is still owed."""
        return self.charges if owed > 0 else 0

    def minimum(self, owed: int) -> int:
        """The minimum payment on `owed`, charges included.

        An unknown minimum counts as the charges alone.
        """
        due = minimum_payment(
            owed,
            card=self.card,
            payment=self.payment,
            percent=self.percent,
            charges=self.charges,
        )
        return self.fee(owed) if due is None else due

    def interest(self, owed: int, month: dt.date) -> int:
        """Interest of `month` on `owed`."""
        if not self.card:
            return monthly_interest(owed, self.annual_rate)
        days = _calendar.month_length(month.year, month.month)
        return daily_interest([owed] * days, self.annual_rate)


@dataclass(frozen=True, slots=True)
class PlanResult:
    """Outcome of `simulate`, with debts in payoff order."""

    order: tuple[PlanDebt, ...]
    monthly_budget: int
    months: tuple[tuple[dt.date, int, int, tuple[int, ...]], ...]
    """(month, payment, interest, balances in `order`) for every month."""
    payoff: tuple[dt.date | None, ...]
    interest: tuple[int, ...]
    paid: tuple[int, ...]
    charges: tuple[int, ...]


def payoff_order(
    debts: Sequence[PlanDebt], strategy: PayoffStrategy
) -> tuple[PlanDebt, ...]:
    """The order in which `strategy` targets extra payments."""
    if strategy is PayoffStrategy.SNOWBALL:
        return tuple(sorted(debts, key=lambda d: (d.owed, -d.annual_rate, d.id)))
    return tuple(sorted(debts, key=lambda d: (-d.annual_rate, d.owed, d.id)))


def simulate(
    debts: Sequence[PlanDebt],
    *,
    first_month: dt.date,
    strategy: PayoffStrategy = PayoffStrategy.AVALANCHE,
    extra: int = 0,
    lump_sums: Mapping[int, int] | None = None,
    rollover: Rollover = Rollover.FULL,
    rollover_percent: Decimal | None = None,
    max_months: int = MAX_PLAN_MONTHS,
) -> PlanResult:
    """Pay off `debts` month by month, starting with `first_month`.

    Every month each debt accrues interest, then gets its minimum payment;
    the rest of the budget goes to the debts in payoff order. The fixed
    charges of a loan are paid every month it is owed, within its minimum
    payment, and do not reduce it. The budget is
    the minimum payments of the first month plus `extra`, adjusted by the
    `rollover` rule as minimum payments shrink, plus the lump sum of the
    month (`lump_sums` maps 0-based month numbers to amounts).
    """
    order = payoff_order(debts, strategy)
    lumps = lump_sums or {}
    balances = [d.owed for d in order]
    interest = [0] * len(order)
    paid = [0] * len(order)
    charges = [0] * len(order)
    payoff: list[dt.date | None] = [None] * len(order)
    initial = sum(d.minimum(d.owed) for d in order)
    share = Decimal(100) if rollover is Rollover.FULL else Decimal(0)
    if rollover is Rollover.PARTIAL:
        share = rollover_percent if rollover_percent is not None else Decimal(50)
    months: list[tuple[dt.date, int, int, tuple[int, ...]]] = []
    month = first_month.replace(day=1)
    for number in range(max_months):
        if not any(balances) or sum(balances) > _RUNAWAY:
            break
        accrued = [
            d.interest(balance, month) if balance else 0
            for d, balance in zip(order, balances, strict=True)
        ]
        balances = [b + a for b, a in zip(balances, accrued, strict=True)]
        fees = [d.fee(b) for d, b in zip(order, balances, strict=True)]
        minimums = [
            min(b, d.minimum(b) - fee) if b else 0
            for d, b, fee in zip(order, balances, fees, strict=True)
        ]
        current = sum(minimums) + sum(fees)
        freed = max(0, initial - current)
        with decimal.localcontext() as context:
            context.prec = 80
            rolled = _round(Decimal(freed) * share / 100)
        left = rolled + extra + lumps.get(number, 0)
        payments = list(minimums)
        for index, balance in enumerate(balances):
            if left <= 0:
                break
            more = min(left, balance - payments[index])
            payments[index] += more
            left -= more
        for index, payment in enumerate(payments):
            balances[index] -= payment
            interest[index] += accrued[index]
            paid[index] += payment + fees[index]
            charges[index] += fees[index]
            if (
                balances[index] == 0
                and payoff[index] is None
                and (payment or accrued[index])
            ):
                payoff[index] = month
        months.append((month, sum(payments) + sum(fees), sum(accrued), tuple(balances)))
        following = _calendar.add_months(month, 1, 1)
        if following is None:
            break
        month = following
    for index, debt in enumerate(order):
        if debt.owed == 0 and payoff[index] is None:
            payoff[index] = first_month.replace(day=1)
        elif balances[index]:
            payoff[index] = None
    return PlanResult(
        order=order,
        monthly_budget=initial + extra,
        months=tuple(months),
        payoff=tuple(payoff),
        interest=tuple(interest),
        paid=tuple(paid),
        charges=tuple(charges),
    )
