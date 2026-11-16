"""Domain types exchanged with the Picciuli API.

All entities returned by the library are immutable, slotted dataclasses: they are
snapshots of the stored data, safe to keep, share between threads or serialize.
To change something, call the matching service method; it returns a new snapshot.

Conventions used everywhere in the library:

* **Amounts** are `int` values in the currency's *minor units* (cents for EUR or
  USD). Use [`picciuli.money`][picciuli.money] to convert from and to text.
* **Signs** follow your point of view: positive means money (or value) coming to
  you, negative means money going away. Liability accounts (credit cards, loans,
  mortgages) therefore have negative balances while you owe money.
* **Dates** are `datetime.date` values without a time component. Date ranges
  are inclusive on both ends.
* **Quantities, prices and exchange rates** are `decimal.Decimal` values with
  at most 8 decimal places. Prices are in the *major* units of the security's
  currency (for example `Decimal("169.86")` euros).
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, TypeAlias

__all__ = [
    "UNSET",
    "Account",
    "AccountBalance",
    "AccountChange",
    "AccountClass",
    "AccountSplit",
    "AccountTrend",
    "AccountType",
    "AccountValuation",
    "Budget",
    "BudgetLine",
    "BudgetReport",
    "CatchUp",
    "Category",
    "CategoryTotal",
    "CostMethod",
    "DebtCharge",
    "DebtLinkKind",
    "DebtPayoff",
    "DebtPlan",
    "DebtStatus",
    "DebtTerms",
    "ExchangeRate",
    "ExternalSplit",
    "GoalAccount",
    "GoalPriority",
    "GoalProgress",
    "GoalReport",
    "GoalStatus",
    "Holding",
    "ImportSummary",
    "LoanPaymentSplit",
    "LumpSum",
    "NetWorth",
    "Occurrence",
    "PayoffStrategy",
    "Period",
    "PeriodChange",
    "PeriodChangeKind",
    "PeriodSummary",
    "PlanMonth",
    "Price",
    "PriceUpdate",
    "Register",
    "RegisterEntry",
    "Rollover",
    "SavingsGoal",
    "Schedule",
    "ScheduleDebt",
    "ScheduleFrequency",
    "ScheduleMode",
    "Security",
    "SecurityKind",
    "Settings",
    "Split",
    "Trade",
    "TradeKind",
    "Transaction",
    "TransactionKind",
    "Unset",
]


class Unset(enum.Enum):
    """Type of the [`UNSET`][picciuli.model.UNSET] sentinel.

    Update methods use `UNSET` as the default value of their optional keyword
    arguments, so that "leave unchanged" can be told apart from "set to `None`".
    """

    UNSET = "UNSET"

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = Unset.UNSET
"""Sentinel meaning "argument not given, keep the current value"."""


class AccountClass(str, enum.Enum):
    """Whether an account holds something you own or something you owe."""

    ASSET = "asset"
    """Money or value you own. Balances are normally positive."""
    LIABILITY = "liability"
    """Money you owe. Balances are normally negative."""


class AccountType(str, enum.Enum):
    """Kind of account. It determines the [`AccountClass`][picciuli.model.AccountClass].

    The type is informational for user interfaces; all accounts follow the same
    rules. Values are stable strings, safe to store or send over an API.
    """

    CHECKING = "checking"
    SAVINGS = "savings"
    CASH = "cash"
    INVESTMENT = "investment"
    OTHER_ASSET = "other_asset"
    CREDIT_CARD = "credit_card"
    LOAN = "loan"
    MORTGAGE = "mortgage"
    OTHER_LIABILITY = "other_liability"

    @property
    def account_class(self) -> AccountClass:
        """The asset or liability class of this account type."""
        if self in _LIABILITY_TYPES:
            return AccountClass.LIABILITY
        return AccountClass.ASSET

    @property
    def holds_goals(self) -> bool:
        """Whether accounts of this type can hold savings goals.

        Cash-like assets can: checking, savings, cash and other assets.
        Investments and liabilities cannot.
        """
        return self in _GOAL_TYPES


_LIABILITY_TYPES: Final = frozenset(
    {
        AccountType.CREDIT_CARD,
        AccountType.LOAN,
        AccountType.MORTGAGE,
        AccountType.OTHER_LIABILITY,
    }
)
_GOAL_TYPES: Final = frozenset(
    {
        AccountType.CHECKING,
        AccountType.SAVINGS,
        AccountType.CASH,
        AccountType.OTHER_ASSET,
    }
)


class GoalPriority(str, enum.Enum):
    """How important a savings goal is. It only decides the display order."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

    @property
    def rank(self) -> int:
        """Sort key: 0 for the most important priority."""
        return _PRIORITY_RANKS[self]


_PRIORITY_RANKS: Final = {
    GoalPriority.HIGH: 0,
    GoalPriority.NORMAL: 1,
    GoalPriority.LOW: 2,
}


class GoalStatus(str, enum.Enum):
    """Where a savings goal stands on the planning day."""

    REACHED = "reached"
    """The saved amount covers the target."""
    SCHEDULED = "scheduled"
    """Not reached, with a target date today or later."""
    UNDATED = "undated"
    """Not reached and without a target date."""
    OVERDUE = "overdue"
    """Not reached, and the target date has passed."""


class TransactionKind(str, enum.Enum):
    """Coarse classification of a transaction, derived from its splits."""

    INCOME = "income"
    """All external splits are positive: money entered your accounts."""
    EXPENSE = "expense"
    """All external splits are negative: money left your accounts."""
    TRANSFER = "transfer"
    """No external splits: money only moved between your accounts."""
    MIXED = "mixed"
    """External splits with both signs, for example a purchase with a refund."""


class TradeKind(str, enum.Enum):
    """Whether a [`Trade`][picciuli.model.Trade] bought or sold shares."""

    BUY = "buy"
    SELL = "sell"


class SecurityKind(str, enum.Enum):
    """Kind of security. Informational, for user interfaces."""

    STOCK = "stock"
    ETF = "etf"
    FUND = "fund"
    BOND = "bond"
    CRYPTO = "crypto"
    OTHER = "other"


class CostMethod(str, enum.Enum):
    """How the cost of sold shares is computed when a sale is recorded.

    The cost removed from the account sets the realized gain of the sale:
    `gain = proceeds - cost`.
    """

    AVERAGE = "average"
    """Weighted average cost of the shares held (as in the Italian
    *regime amministrato*)."""
    FIFO = "fifo"
    """First in, first out: the oldest shares are sold first."""


class ScheduleFrequency(str, enum.Enum):
    """The unit a [`Schedule`][picciuli.model.Schedule] repeats by."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class ScheduleMode(str, enum.Enum):
    """What happens when an occurrence of a schedule is due."""

    AUTO = "auto"
    """It is recorded on its own by
    [`catch_up`][picciuli.services.ScheduleService.catch_up]."""
    CONFIRM = "confirm"
    """It waits until it is [posted][picciuli.services.ScheduleService.post]
    (possibly with a different amount) or
    [skipped][picciuli.services.ScheduleService.skip]."""


class DebtLinkKind(str, enum.Enum):
    """How a [`Schedule`][picciuli.model.Schedule] is tied to a debt."""

    LOAN_PAYMENT = "loan_payment"
    """A payment into a loan: each occurrence is split into principal and
    interest from the balance owed on its day."""
    CARD_INTEREST = "card_interest"
    """The interest charge of a credit card, proposed on each statement day
    and managed by the card's [`DebtTerms`][picciuli.model.DebtTerms]."""
    CARD_MIN_PAYMENT = "card_min_payment"
    """The minimum payment of a credit card, proposed on each due day and
    managed by the card's [`DebtTerms`][picciuli.model.DebtTerms]."""


class PayoffStrategy(str, enum.Enum):
    """Which debt a [`DebtPlan`][picciuli.model.DebtPlan] pays off first."""

    SNOWBALL = "snowball"
    """Smallest balance first: quick wins that keep you motivated."""
    AVALANCHE = "avalanche"
    """Highest interest rate first: the least interest overall."""


class Rollover(str, enum.Enum):
    """What happens to the payment of a debt once it is paid off."""

    FULL = "full"
    """It goes to the next debt: the total monthly payment stays the same
    (classic snowball or avalanche). Fastest and cheapest, but the monthly
    outlay never drops until every debt is paid."""
    NONE = "none"
    """It is freed up: the total monthly payment drops as debts close. More
    cash every month, but slower and more interest."""
    PARTIAL = "partial"
    """A percentage of it goes to the next debt and the rest is freed up."""


class PeriodChangeKind(str, enum.Enum):
    """What [`PeriodService.regenerate`][picciuli.services.PeriodService] does."""

    CREATE = "create"
    """A new period is added."""
    UPDATE = "update"
    """An existing period gets new dates or a new name; its budgets are kept."""
    KEEP = "keep"
    """An existing period overlaps one that is already regenerated; it is left
    unchanged."""


@dataclass(frozen=True, slots=True)
class DebtCharge:
    """A fixed charge included in every payment of a loan.

    For example an insurance premium or a collection fee: it is an expense,
    so it does not reduce the debt.

    Attributes:
        amount: Positive amount charged on every payment.
        category_id: Category of the expense, or `None`.
        label: Memo of the split, for example `"Insurance"`, or `None`.
    """

    amount: int
    category_id: int | None = None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class DebtTerms:
    """Interest and payment terms of a liability account.

    Loans, mortgages and other liabilities accrue interest every month on the
    balance owed (`annual_rate / 12`). Credit cards accrue it every day: each
    statement charges the average daily balance owed during the cycle times
    `annual_rate / 365`, unless the previous statement was paid in full by its
    due day (grace period).

    Attributes:
        annual_rate: Nominal annual interest rate in percent, for example
            `Decimal("19.9")`.
        payment: Loans: the fixed monthly payment. Credit cards: the smallest
            minimum payment (floor). `None` if unknown.
        payment_percent: Credit cards only: the minimum payment as a
            percentage of the statement balance, for example `Decimal(3)`.
        due_day: Day of the month payments are due (1 to 31; shorter months
            use their last day), or `None`.
        statement_day: Credit cards only: day of the month the statement
            closes, or `None`.
        credit_limit: Credit cards only: the credit limit, or `None`.
        payment_account_id: Account the payments usually come from, or `None`.
        interest_category_id: Category of the interest expense, or `None`.
        propose_interest: Credit cards only: whether an interest charge waits
            for confirmation on every statement day.
        propose_minimum: Credit cards only: whether the minimum payment waits
            for confirmation on every due day.
        charges: Loans only: fixed charges included in every payment, such
            as an insurance premium; at most 10. A payment pays the interest
            first, then the charges in order, and the rest reduces the debt.
    """

    annual_rate: Decimal
    payment: int | None = None
    payment_percent: Decimal | None = None
    due_day: int | None = None
    statement_day: int | None = None
    credit_limit: int | None = None
    payment_account_id: int | None = None
    interest_category_id: int | None = None
    propose_interest: bool = False
    propose_minimum: bool = False
    charges: tuple[DebtCharge, ...] = ()


@dataclass(frozen=True, slots=True)
class Account:
    """A place where money is kept or owed.

    Attributes:
        id: Unique identifier.
        name: Unique display name (case-insensitive).
        type: Kind of account.
        opening_balance: Balance before the first transaction, in minor units.
        opening_date: Day the opening balance applies from. `None` means the
            opening balance applies since the beginning of time. Transactions
            cannot be dated before this day.
        notes: Free text.
        position: 1-based display position among all accounts.
        closed_on: Day the account was closed, or `None` while it is open.
        debt_terms: Interest and payment terms of a liability, or `None`.
    """

    id: int
    name: str
    type: AccountType
    opening_balance: int
    opening_date: dt.date | None
    notes: str | None
    position: int
    closed_on: dt.date | None
    debt_terms: DebtTerms | None = None

    @property
    def account_class(self) -> AccountClass:
        """Asset or liability, derived from the account `type`."""
        return self.type.account_class

    @property
    def is_closed(self) -> bool:
        """Whether the account has been closed (archived)."""
        return self.closed_on is not None


@dataclass(frozen=True, slots=True)
class SavingsGoal:
    """Money you want to set aside in one account, for example a holiday.

    An account can hold several goals. The saved amount is assigned by hand:
    it does not move money and no transaction changes it, so it can exceed the
    target or (together with the other goals) the account balance.

    Attributes:
        id: Unique identifier.
        account_id: Account holding the money.
        name: Display name, unique within the account (case-insensitive).
        target_amount: Amount to reach, in minor units (positive).
        saved_amount: Amount already set aside, in minor units (zero or more).
        target_date: Day the target should be reached, or `None`.
        priority: Importance, used to order the goals of an account.
    """

    id: int
    account_id: int
    name: str
    target_amount: int
    saved_amount: int
    target_date: dt.date | None
    priority: GoalPriority


@dataclass(frozen=True, slots=True)
class GoalProgress:
    """A savings goal and what it still needs on the planning day.

    Attributes:
        goal: The goal.
        remaining: What is still missing: the target minus the saved amount,
            or zero once reached.
        status: Reached, scheduled, undated or overdue.
        months_left: Calendar months to save in, counting the current month
            and the month of the target date; `None` unless `scheduled`.
        monthly_amount: What to set aside every month to reach the target on
            time (the remaining amount divided by `months_left`, rounded up);
            zero once reached, `None` for undated or overdue goals.
    """

    goal: SavingsGoal
    remaining: int
    status: GoalStatus
    months_left: int | None
    monthly_amount: int | None


@dataclass(frozen=True, slots=True)
class GoalAccount:
    """The savings goals of one account, compared with its balance.

    Attributes:
        account: The account.
        balance: Balance at the end of the planning day.
        assigned: Total saved amount of its goals.
        unassigned: Money of the balance not assigned to any goal.
        shortfall: How much the goals claim beyond the balance; non-zero
            means the account holds less money than its goals say.
        goals: Its goals, by priority.
    """

    account: Account
    balance: int
    assigned: int
    unassigned: int
    shortfall: int
    goals: tuple[GoalProgress, ...]


@dataclass(frozen=True, slots=True)
class GoalReport:
    """Every savings goal on a planning day, grouped by account.

    Attributes:
        today: The planning day.
        accounts: Accounts with at least one goal, in display order.
    """

    today: dt.date
    accounts: tuple[GoalAccount, ...]


@dataclass(frozen=True, slots=True)
class Category:
    """A label that classifies external cash flows.

    Categories form a two-level tree: top-level categories may contain
    subcategories, and subcategories cannot have children.

    Attributes:
        id: Unique identifier.
        name: Unique display name (case-insensitive).
        symbol: Short label (at most 12 characters) for compact displays.
        parent_id: Parent category, or `None` for a top-level category.
        position: 1-based display position among its siblings.
    """

    id: int
    name: str
    symbol: str
    parent_id: int | None
    position: int


@dataclass(frozen=True, slots=True)
class Period:
    """A user-defined, named range of days, for example a month or a holiday.

    Periods may overlap.

    Attributes:
        id: Unique identifier.
        name: Display name; not necessarily unique.
        start: First day of the period (inclusive).
        end: Last day of the period (inclusive), or `None` if still open.
    """

    id: int
    name: str
    start: dt.date
    end: dt.date | None

    def contains(self, day: dt.date) -> bool:
        """Return whether `day` falls inside the period."""
        return self.start <= day and (self.end is None or day <= self.end)


@dataclass(frozen=True, slots=True)
class Budget:
    """A spending allowance for a category during a period.

    A budget on a top-level category also covers its subcategories.

    Attributes:
        id: Unique identifier.
        category_id: Budgeted category.
        period_id: Period the budget applies to.
        amount: Allowance in minor units (zero or positive).
    """

    id: int
    category_id: int
    period_id: int
    amount: int


@dataclass(frozen=True, slots=True)
class AccountSplit:
    """The part of a transaction that changes the balance of one account.

    On an investment account a split can also move shares of a security: a
    purchase adds a positive `quantity` and its cost to the account, a sale
    removes a negative `quantity` and the cost of those shares. The amount
    may be zero only when shares move, for example for a stock split or bonus
    shares.

    Attributes:
        account_id: Affected account.
        amount: Signed change of the account balance (never zero unless a
            security is given).
        memo: Optional note for this split.
        security_id: Security whose shares move, or `None` for cash only.
        quantity: Signed number of shares (never zero), required with
            `security_id` and forbidden without it.
    """

    account_id: int
    amount: int
    memo: str | None = None
    security_id: int | None = None
    quantity: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ExternalSplit:
    """The part of a transaction that crosses the boundary of your accounts.

    It is money coming from or going to the outside world: income, expenses,
    interest, fees and so on.

    Attributes:
        amount: Signed effect on you: positive for income, negative for an
            expense (never zero).
        category_id: Category of the flow, or `None` if uncategorized.
        memo: Optional note for this split.
    """

    amount: int
    category_id: int | None = None
    memo: str | None = None


Split: TypeAlias = AccountSplit | ExternalSplit
"""Either kind of transaction split."""


@dataclass(frozen=True, slots=True)
class Trade:
    """The details of a purchase or sale of shares, as they were entered.

    Transactions recorded with
    [`record_buy`][picciuli.services.InvestmentService.record_buy] or
    [`record_sell`][picciuli.services.InvestmentService.record_sell] keep these
    arguments next to the splits they produced, so that they can be edited
    again with the same form. Replacing the splits of the transaction by hand
    turns it into an ordinary transaction without a trade.

    Attributes:
        kind: Purchase or sale.
        account_id: Investment account holding the shares.
        security_id: The security traded.
        quantity: Positive number of shares.
        amount: Positive cost of a purchase, or gross proceeds of a sale.
        other_account_id: Account paying for a purchase or receiving the
            money of a sale, or `None` for the investment account's own cash.
        fee: Commission (zero or positive).
        fee_category_id: Category of the fee expense.
        tax: Tax withheld on a sale (zero or positive; always zero for a
            purchase).
        tax_category_id: Category of the tax expense (sales only).
        gain_category_id: Category of the realized gain or loss (sales only).
    """

    kind: TradeKind
    account_id: int
    security_id: int
    quantity: Decimal
    amount: int
    other_account_id: int | None = None
    fee: int = 0
    fee_category_id: int | None = None
    tax: int = 0
    tax_category_id: int | None = None
    gain_category_id: int | None = None


@dataclass(frozen=True, slots=True)
class Transaction:
    """A dated, balanced set of splits.

    The account splits always add up to the same total as the external splits.
    For example:

    | Situation            | Splits                                                |
    |----------------------|-------------------------------------------------------|
    | Grocery expense      | checking -50, external -50 (Food)                     |
    | Salary               | checking +2000, external +2000 (Salary)               |
    | Transfer to savings  | checking -100, savings +100                           |
    | Mortgage payment     | checking -500, mortgage +400, external -100 (Interest)|
    | Split card purchase  | card -100, external -60 (Food), external -40 (Home)   |
    | Buy 1 share          | checking -35, investment +35 (+1 share)               |

    Attributes:
        id: Unique identifier.
        date: Day the transaction happened.
        description: Short description, for example a payee.
        notes: Free text.
        splits: Splits in their stored order.
        trade: The purchase or sale of shares the splits were built from,
            or `None` for any other transaction.
        schedule_id: The [`Schedule`][picciuli.model.Schedule] that recorded
            the transaction, or `None`. It becomes `None` when the schedule
            is deleted.
    """

    id: int
    date: dt.date
    description: str | None
    notes: str | None
    splits: tuple[Split, ...]
    trade: Trade | None = None
    schedule_id: int | None = None

    @property
    def account_splits(self) -> tuple[AccountSplit, ...]:
        """Splits that change account balances."""
        return tuple(s for s in self.splits if isinstance(s, AccountSplit))

    @property
    def external_splits(self) -> tuple[ExternalSplit, ...]:
        """Splits that cross the boundary of your accounts."""
        return tuple(s for s in self.splits if isinstance(s, ExternalSplit))

    @property
    def net_amount(self) -> int:
        """Total effect on you: the sum of the external splits."""
        return sum(s.amount for s in self.external_splits)

    @property
    def kind(self) -> TransactionKind:
        """Income, expense, transfer or mixed, derived from the external splits."""
        return _kind(self.external_splits)


def _kind(external: tuple[ExternalSplit, ...]) -> TransactionKind:
    if not external:
        return TransactionKind.TRANSFER
    if all(s.amount > 0 for s in external):
        return TransactionKind.INCOME
    if all(s.amount < 0 for s in external):
        return TransactionKind.EXPENSE
    return TransactionKind.MIXED


@dataclass(frozen=True, slots=True)
class Schedule:
    """A recurring transaction: a template of splits and a repetition rule.

    Occurrences fall every `every` days, weeks, months or years starting
    from the first one. Monthly and yearly schedules fall on `day_of_month`,
    or on the last day of shorter months (31 means "the last day of every
    month"). A schedule finishes after its `end` day or once `remaining`
    reaches zero.

    The splits follow the rules of [`Transaction`][picciuli.model.Transaction]
    but cannot move shares.

    Attributes:
        id: Unique identifier.
        description: Description of the transactions it records.
        notes: Notes of the transactions it records.
        splits: Template of the splits of each transaction.
        frequency: Unit of repetition.
        every: Number of units between two occurrences (1 or more).
        day_of_month: Day of the month of monthly and yearly occurrences
            (1 to 31), or `None` for daily and weekly schedules.
        next_date: Day of the next occurrence, or `None` once finished.
        end: Last day an occurrence may fall on, or `None`.
        remaining: Occurrences left including `next_date`, or `None` for no
            limit.
        mode: Whether due occurrences are recorded on their own or wait for
            confirmation.
        paused: Whether the schedule is suspended: paused schedules are
            neither caught up nor projected.
        last_error: Why the last automatic posting failed, or `None`.
        debt: The debt the schedule pays or charges, or `None`. Schedules of
            credit card interest and minimum payments have no template
            splits: their amounts are computed for each occurrence.
    """

    id: int
    description: str | None
    notes: str | None
    splits: tuple[Split, ...]
    frequency: ScheduleFrequency
    every: int
    day_of_month: int | None
    next_date: dt.date | None
    end: dt.date | None
    remaining: int | None
    mode: ScheduleMode
    paused: bool
    last_error: str | None
    debt: ScheduleDebt | None = None

    @property
    def is_finished(self) -> bool:
        """Whether the schedule has no occurrence left."""
        return self.next_date is None

    @property
    def net_amount(self) -> int:
        """Total effect on you of each occurrence: the sum of the external splits."""
        return sum(s.amount for s in self.splits if isinstance(s, ExternalSplit))

    @property
    def kind(self) -> TransactionKind:
        """Income, expense, transfer or mixed, derived from the external splits."""
        return _kind(tuple(s for s in self.splits if isinstance(s, ExternalSplit)))


@dataclass(frozen=True, slots=True)
class ScheduleDebt:
    """The debt a [`Schedule`][picciuli.model.Schedule] pays or charges.

    Attributes:
        kind: Loan payment, credit card interest or credit card minimum
            payment.
        account_id: The loan or credit card account.
        interest_category_id: Loan payments only: category of the interest
            part, or `None` to use the one of the loan's
            [`DebtTerms`][picciuli.model.DebtTerms].
    """

    kind: DebtLinkKind
    account_id: int
    interest_category_id: int | None = None


@dataclass(frozen=True, slots=True)
class Occurrence:
    """A day on which a schedule records (or will record) a transaction.

    Attributes:
        schedule_id: The schedule.
        date: Day of the occurrence.
        amount: For schedules tied to a debt, the predicted amount computed
            from the transactions recorded so far: the total payment of a
            loan, the interest charge or the minimum payment still due on a
            credit card. `None` for other schedules.
        splits: For schedules tied to a debt, the predicted splits, or `None`
            when they follow the template or the paying account is unknown.
    """

    schedule_id: int
    date: dt.date
    amount: int | None = None
    splits: tuple[Split, ...] | None = None


@dataclass(frozen=True, slots=True)
class CatchUp:
    """Outcome of [`catch_up`][picciuli.services.ScheduleService.catch_up].

    Attributes:
        posted: Transactions recorded by automatic schedules, by date.
        due: Occurrences of schedules waiting for confirmation, up to the
            given day, by date.
        failed: Automatic schedules that could not record a due occurrence;
            see their `last_error`.
        skipped: Credit card occurrences with nothing to charge or pay (no
            interest thanks to the grace period, or a minimum payment already
            covered), skipped on their own.
    """

    posted: tuple[Transaction, ...]
    due: tuple[Occurrence, ...]
    failed: tuple[Schedule, ...]
    skipped: tuple[Occurrence, ...] = ()


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """An account with its balance on a given day.

    Attributes:
        account: The account.
        balance: Balance in minor units.
    """

    account: Account
    balance: int


@dataclass(frozen=True, slots=True)
class AccountTrend:
    """How the balance of an account has been moving, to forecast it.

    Attributes:
        account: The account.
        balance: Balance including every transaction.
        months: Number of complete months averaged: the last 3 before the
            current one, or fewer when the first transaction of the account
            is more recent. `0` when there is no such month.
        average_flow: Average net change of the balance per month over those
            months, in minor units (rounded), not counting the opening
            balance; `None` when `months` is `0`.
        low_point: While the balance is negative, the lowest balance reached
            since it last went below zero (the start of the current debt);
            `None` when the balance is not negative.
    """

    account: Account
    balance: int
    months: int
    average_flow: int | None
    low_point: int | None


@dataclass(frozen=True, slots=True)
class NetWorth:
    """Totals of all account balances on a given day.

    Attributes:
        as_of: Day of the computation, or `None` for "including every transaction".
        assets: Sum of the balances of asset accounts.
        liabilities: Sum of the balances of liability accounts (normally negative).
    """

    as_of: dt.date | None
    assets: int
    liabilities: int

    @property
    def net_worth(self) -> int:
        """Assets plus liabilities."""
        return self.assets + self.liabilities


@dataclass(frozen=True, slots=True)
class RegisterEntry:
    """One transaction as seen from a single account.

    Attributes:
        transaction: The full transaction.
        amount: Total change of the account balance caused by the transaction.
        balance: Running balance of the account after the transaction.
    """

    transaction: Transaction
    amount: int
    balance: int


@dataclass(frozen=True, slots=True)
class Register:
    """The ledger of one account over a range of days.

    Attributes:
        account: The account.
        starting_balance: Balance before the first entry of the range,
            including the opening balance if it applies.
        entries: Transactions in chronological order with running balances.
    """

    account: Account
    starting_balance: int
    entries: tuple[RegisterEntry, ...]

    @property
    def ending_balance(self) -> int:
        """Balance after the last entry of the range."""
        return self.entries[-1].balance if self.entries else self.starting_balance


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    """External cash flows of one category over a range of days.

    Attributes:
        category: The category.
        amount: Net flow of the category itself (signed).
        total: Net flow including subcategories (equals `amount` for
            subcategories).
    """

    category: Category
    amount: int
    total: int


@dataclass(frozen=True, slots=True)
class AccountChange:
    """How an account balance changed over a range of days.

    Attributes:
        account: The account.
        opening: Balance before the first day.
        closing: Balance at the end of the last day.
    """

    account: Account
    opening: int
    closing: int

    @property
    def change(self) -> int:
        """Closing minus opening balance."""
        return self.closing - self.opening


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    """Totals of a period: flows by category and account balance changes.

    Transfers between your own accounts never appear in category totals, income
    or expenses; they only show up in the account changes.

    Attributes:
        period: The summarized period.
        categories: Every category in display order (top-level categories each
            followed by their subcategories), including those without flows.
        uncategorized: Net flow of external splits without a category.
        income: Sum of the categories with a positive net flow, plus the
            positive uncategorized splits.
        expenses: Sum of the categories with a negative net flow, plus the
            negative uncategorized splits (zero or negative).
        accounts: Balance changes of the accounts open during the period.
    """

    period: Period
    categories: tuple[CategoryTotal, ...]
    uncategorized: int
    income: int
    expenses: int
    accounts: tuple[AccountChange, ...]

    @property
    def net(self) -> int:
        """Income plus expenses."""
        return self.income + self.expenses


@dataclass(frozen=True, slots=True)
class PeriodChange:
    """One step of regenerating periods from the monthly period settings.

    Attributes:
        kind: Whether the period is created, updated or kept.
        period: The existing period before the change, or `None` when one is
            created.
        name: Name after the change.
        start: First day after the change.
        end: Last day after the change, or `None` if still open.
    """

    kind: PeriodChangeKind
    period: Period | None
    name: str
    start: dt.date
    end: dt.date | None


@dataclass(frozen=True, slots=True)
class BudgetLine:
    """Status of one budget.

    Attributes:
        budget: The budget.
        category: The budgeted category.
        actual: Net external flow of the category during the period, including
            subcategories for a top-level category. Spending is negative.
        remaining: `budget.amount + actual`; negative when overspent.
    """

    budget: Budget
    category: Category
    actual: int
    remaining: int


@dataclass(frozen=True, slots=True)
class BudgetReport:
    """Status of all budgets of a period.

    The totals count every flow once: when both a top-level category and one of
    its subcategories have a budget, the subcategory line is excluded from the
    totals because the parent budget already covers it.

    Attributes:
        period: The period.
        lines: One line per budget, in category display order.
        total_budget: Sum of the budget amounts.
        total_actual: Sum of the actual flows.
        total_remaining: Sum of the remaining amounts.
    """

    period: Period
    lines: tuple[BudgetLine, ...]
    total_budget: int
    total_actual: int
    total_remaining: int


@dataclass(frozen=True, slots=True)
class Settings:
    """Book-wide settings.

    Attributes:
        currency: Currency symbol or code shown by user interfaces.
        minor_digits: Number of decimal digits of the currency (2 for cents).
        currency_code: ISO 4217 code of the book currency (for example
            `"EUR"`), used to convert the value of securities quoted in other
            currencies. `None` if unknown.
        cost_method: How the cost of sold shares is computed.
        price_provider: Identifier of the price provider used to refresh
            security prices (see [`PriceProvider`][picciuli.prices.PriceProvider]).
        rate_provider: Identifier of the exchange-rate provider used to refresh
            exchange rates (see
            [`ExchangeRateProvider`][picciuli.rates.ExchangeRateProvider]).
        period_start_day: Day of the month (1 to 31, for example your
            payday) on which monthly periods start, or `None` when periods
            are only created by hand. See
            [`PeriodService.ensure_monthly`][picciuli.services.PeriodService.ensure_monthly].
        period_weekend_shift: Whether a monthly period that would start on a
            Saturday or Sunday starts on the Friday before instead.
    """

    currency: str
    minor_digits: int
    currency_code: str | None = None
    cost_method: CostMethod = CostMethod.AVERAGE
    price_provider: str = "yahoo"
    rate_provider: str = "yahoo"
    period_start_day: int | None = None
    period_weekend_shift: bool = True


@dataclass(frozen=True, slots=True)
class Security:
    """Something you can hold shares of: a stock, an ETF, a fund...

    Attributes:
        id: Unique identifier.
        name: Unique display name (case-insensitive).
        symbol: Symbol used by the price provider (for example `"VWCE.DE"`
            for Yahoo Finance), or `None` if prices are entered by hand.
        isin: International Securities Identification Number, or `None`.
        currency: ISO 4217 code of the currency the security is quoted in.
        kind: Kind of security.
        notes: Free text.
    """

    id: int
    name: str
    symbol: str | None
    isin: str | None
    currency: str
    kind: SecurityKind
    notes: str | None


@dataclass(frozen=True, slots=True)
class Price:
    """The price of one share of a security on a day.

    A security has at most one price per day; refreshing during the day
    replaces it with the latest quote.

    Attributes:
        security_id: The security.
        date: Day of the price.
        price: Price of one share in the security's currency (major units).
        source: Where the price comes from (a provider identifier), or `None`
            if entered by hand.
    """

    security_id: int
    date: dt.date
    price: Decimal
    source: str | None = None


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    """The value of one unit of a foreign currency in the book currency.

    Attributes:
        currency: ISO 4217 code of the foreign currency.
        date: Day of the rate.
        rate: Book currency per one unit of `currency` (major units).
    """

    currency: str
    date: dt.date
    rate: Decimal


@dataclass(frozen=True, slots=True)
class Holding:
    """Shares of one security held in an investment account on a day.

    Attributes:
        security: The security.
        quantity: Number of shares held.
        cost_basis: What the shares cost, in minor units of the book currency:
            the sum of the amounts of the splits that moved them.
        price: Latest known price on or before the day, or `None`.
        price_date: Day of `price`, or `None`.
        exchange_rate: Rate used to convert the price into the book currency
            (`1` for securities quoted in the book currency), or `None` if
            unknown.
        market_value: `quantity * price * exchange_rate` in minor units of the
            book currency, or `None` when the price or the rate is unknown.
    """

    security: Security
    quantity: Decimal
    cost_basis: int
    price: Decimal | None
    price_date: dt.date | None
    exchange_rate: Decimal | None
    market_value: int | None

    @property
    def converted_price(self) -> Decimal | None:
        """Price of one share in the book currency (major units), if known."""
        if self.price is None or self.exchange_rate is None:
            return None
        return self.price * self.exchange_rate

    @property
    def unrealized_gain(self) -> int | None:
        """Market value minus cost basis, or `None` without a market value."""
        if self.market_value is None:
            return None
        return self.market_value - self.cost_basis


@dataclass(frozen=True, slots=True)
class AccountValuation:
    """The market value of an account on a day.

    The ledger balance of an investment account is its uninvested cash plus the
    cost basis of its holdings. The market value replaces that cost basis with
    the current value of the shares; price changes are never transactions.

    Attributes:
        account: The account.
        as_of: Day of the valuation, or `None` for "including every
            transaction and the latest prices".
        balance: Ledger balance, as returned by
            [`AccountService.balance`][picciuli.services.AccountService.balance].
        holdings: Securities with a non-zero quantity or cost basis.
    """

    account: Account
    as_of: dt.date | None
    balance: int
    holdings: tuple[Holding, ...]

    @property
    def cost_basis(self) -> int:
        """Total cost basis of the holdings."""
        return sum(h.cost_basis for h in self.holdings)

    @property
    def cash(self) -> int:
        """Uninvested money: the balance minus the cost basis of the holdings."""
        return self.balance - self.cost_basis

    @property
    def market_value(self) -> int:
        """Cash plus the market value of the holdings.

        Holdings without a known market value are counted at cost basis.
        """
        return self.cash + sum(
            h.cost_basis if h.market_value is None else h.market_value
            for h in self.holdings
        )

    @property
    def unrealized_gain(self) -> int:
        """Market value minus ledger balance."""
        return self.market_value - self.balance

    @property
    def is_complete(self) -> bool:
        """Whether every holding has a known market value."""
        return all(h.market_value is not None for h in self.holdings)


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Outcome of refreshing prices from a price provider.

    Attributes:
        prices: Prices stored (new or replaced).
        exchange_rates: Exchange rates stored (new or replaced).
        errors: One message per security or currency that could not be
            refreshed; the others are still stored.
    """

    prices: tuple[Price, ...]
    exchange_rates: tuple[ExchangeRate, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImportSummary:
    """Outcome of [`Book.import_from`][picciuli.Book.import_from].

    Every count is the number of rows *added* to the book; entities that were
    already present (and therefore reused) are not counted.

    Attributes:
        replaced: Whether the previous content was erased before importing.
        accounts: Accounts added.
        categories: Categories added.
        securities: Securities added.
        prices: Prices added.
        exchange_rates: Exchange rates added.
        periods: Periods added.
        budgets: Budgets added.
        transactions: Transactions added.
        duplicates: Transactions skipped because an identical one already
            existed.
        schedules: Recurring transactions added.
        goals: Savings goals added.
    """

    replaced: bool
    accounts: int
    categories: int
    securities: int
    prices: int
    exchange_rates: int
    periods: int
    budgets: int
    transactions: int
    duplicates: int
    schedules: int = 0
    goals: int = 0


@dataclass(frozen=True, slots=True)
class DebtStatus:
    """A liability with interest and payment terms, and when it will be paid off.

    Attributes:
        account: The account, with its
            [`debt_terms`][picciuli.model.Account].
        balance: Balance including every transaction up to today (negative
            while you owe money).
        minimum_payment: What is due every month now: the fixed payment of
            a loan (charges included) or the minimum payment of a credit card
            on the current balance; `None` when the terms do not say.
        next_due: Next due day on or after today, or `None` without a due day.
        payoff: First day of the month in which the debt is paid off at the
            minimum payment, with interest; `None` if it never is (the payment
            does not cover the interest) or the minimum payment is unknown.
        interest_to_payoff: Interest paid until then, or `None` with `payoff`.
        charges_to_payoff: Fixed charges of a loan paid until then, or `None`
            with `payoff`.
    """

    account: Account
    balance: int
    minimum_payment: int | None
    next_due: dt.date | None
    payoff: dt.date | None
    interest_to_payoff: int | None
    charges_to_payoff: int | None = None

    @property
    def owed(self) -> int:
        """The amount owed: the opposite of a negative balance, else zero."""
        return max(0, -self.balance)


@dataclass(frozen=True, slots=True)
class LumpSum:
    """A one-off extra payment in a [`DebtPlan`][picciuli.model.DebtPlan].

    Attributes:
        date: Any day of the month the payment is made in.
        amount: Positive amount.
    """

    date: dt.date
    amount: int


@dataclass(frozen=True, slots=True)
class DebtPayoff:
    """How one debt is paid off in a [`DebtPlan`][picciuli.model.DebtPlan].

    Attributes:
        account_id: The liability account.
        order: 1-based position in the payoff order of the strategy.
        balance: Amount owed at the start of the plan.
        payoff: First day of the month the debt is paid off, or `None` if it
            is not paid off within the horizon of the plan.
        interest: Interest accrued until then.
        paid: Total paid into the debt, fixed charges included.
        charges: Fixed charges of a loan paid until then.
    """

    account_id: int
    order: int
    balance: int
    payoff: dt.date | None
    interest: int
    paid: int
    charges: int = 0


@dataclass(frozen=True, slots=True)
class PlanMonth:
    """One month of a [`DebtPlan`][picciuli.model.DebtPlan].

    Attributes:
        month: First day of the month.
        payment: Total paid into the debts, fixed charges included.
        interest: Total interest accrued.
        balance: Total owed at the end of the month.
        balances: Amount owed on each debt at the end of the month, in the
            order of [`DebtPlan.debts`][picciuli.model.DebtPlan].
    """

    month: dt.date
    payment: int
    interest: int
    balance: int
    balances: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DebtPlan:
    """A month-by-month simulation of paying off every debt.

    Every month each debt accrues interest and gets its minimum payment; the
    rest of the monthly budget (the minimum payments of the first month plus
    the extra payment, and the lump sums of the month) goes to the debts in
    the order of the strategy. See [`Rollover`][picciuli.model.Rollover] for
    what happens to the payment of a debt once it is paid off.

    Attributes:
        strategy: Which debt is paid off first.
        rollover: What happens to the payment of a paid-off debt.
        rollover_percent: With `Rollover.PARTIAL`, the percentage of it that
            goes to the next debt; `None` otherwise.
        extra: Extra payment every month, on top of the minimum payments.
        monthly_budget: Total paid in the first month without lump sums: the
            minimum payments plus `extra`.
        debts: Each debt, in payoff order.
        months: Every month until the last debt is paid off (or the horizon).
        payoff: First day of the month the last debt is paid off, or `None`
            if some debt is not paid off within the horizon.
        total_interest: Interest accrued over the plan.
        total_paid: Total paid over the plan, fixed charges included.
        total_charges: Fixed charges of loans paid over the plan.
    """

    strategy: PayoffStrategy
    rollover: Rollover
    rollover_percent: Decimal | None
    extra: int
    monthly_budget: int
    debts: tuple[DebtPayoff, ...]
    months: tuple[PlanMonth, ...]
    payoff: dt.date | None
    total_interest: int
    total_paid: int
    total_charges: int = 0


@dataclass(frozen=True, slots=True)
class LoanPaymentSplit:
    """How a payment into a loan divides into interest, charges and principal.

    Attributes:
        account_id: The loan.
        date: Day of the payment.
        amount: The whole payment.
        owed: Amount owed at the start of the day.
        interest: Interest of the month on `owed`, at most `amount`.
        principal: What reduces the debt: `amount` less the interest and the
            charges.
        charges: The fixed charges of the loan's terms included in the
            payment, in order, with the amounts actually charged: what is
            left after the interest, so a small payment can leave some out.
    """

    account_id: int
    date: dt.date
    amount: int
    owed: int
    interest: int
    principal: int
    charges: tuple[DebtCharge, ...] = ()
