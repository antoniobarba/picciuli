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
    "AccountType",
    "AccountValuation",
    "Budget",
    "BudgetLine",
    "BudgetReport",
    "Category",
    "CategoryTotal",
    "CostMethod",
    "ExchangeRate",
    "ExternalSplit",
    "Holding",
    "ImportSummary",
    "NetWorth",
    "Period",
    "PeriodSummary",
    "Price",
    "PriceUpdate",
    "Register",
    "RegisterEntry",
    "Security",
    "SecurityKind",
    "Settings",
    "Split",
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


_LIABILITY_TYPES: Final = frozenset(
    {
        AccountType.CREDIT_CARD,
        AccountType.LOAN,
        AccountType.MORTGAGE,
        AccountType.OTHER_LIABILITY,
    }
)


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
        goal: Optional target balance, for example a savings goal.
        notes: Free text.
        position: 1-based display position among all accounts.
        closed_on: Day the account was closed, or `None` while it is open.
    """

    id: int
    name: str
    type: AccountType
    opening_balance: int
    opening_date: dt.date | None
    goal: int | None
    notes: str | None
    position: int
    closed_on: dt.date | None

    @property
    def account_class(self) -> AccountClass:
        """Asset or liability, derived from the account `type`."""
        return self.type.account_class

    @property
    def is_closed(self) -> bool:
        """Whether the account has been closed (archived)."""
        return self.closed_on is not None


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
    """

    id: int
    date: dt.date
    description: str | None
    notes: str | None
    splits: tuple[Split, ...]

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
        external = self.external_splits
        if not external:
            return TransactionKind.TRANSFER
        if all(s.amount > 0 for s in external):
            return TransactionKind.INCOME
        if all(s.amount < 0 for s in external):
            return TransactionKind.EXPENSE
        return TransactionKind.MIXED


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
        income: Sum of all positive external splits.
        expenses: Sum of all negative external splits (zero or negative).
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
    """

    currency: str
    minor_digits: int
    currency_code: str | None = None
    cost_method: CostMethod = CostMethod.AVERAGE
    price_provider: str = "yahoo"
    rate_provider: str = "yahoo"


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
