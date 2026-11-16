"""Picciuli: a personal budgeting and money tracking engine.

Everything starts from a [`Book`][picciuli.Book]:

```python
import datetime as dt
from picciuli import AccountType, Book

with Book.open("finance.db") as book:
    checking = book.accounts.create("Checking", AccountType.CHECKING)
    book.transactions.record_income(dt.date.today(), 250000, account_id=checking.id)
```

The names exported here form the public API and follow semantic versioning.
Modules whose name starts with an underscore are private.
"""

from importlib.metadata import PackageNotFoundError, version

from picciuli.book import Book
from picciuli.errors import (
    ConflictError,
    NotFoundError,
    PicciuliError,
    PriceProviderError,
    SchemaVersionError,
    ValidationError,
)
from picciuli.model import (
    UNSET,
    Account,
    AccountBalance,
    AccountChange,
    AccountClass,
    AccountSplit,
    AccountTrend,
    AccountType,
    AccountValuation,
    Budget,
    BudgetLine,
    BudgetReport,
    Category,
    CategoryTotal,
    CostMethod,
    ExchangeRate,
    ExternalSplit,
    Holding,
    ImportSummary,
    NetWorth,
    Period,
    PeriodSummary,
    Price,
    PriceUpdate,
    Register,
    RegisterEntry,
    Security,
    SecurityKind,
    Settings,
    Split,
    Trade,
    TradeKind,
    Transaction,
    TransactionKind,
    Unset,
)

try:
    __version__ = version("picciuli")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0+unknown"

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
    "Book",
    "Budget",
    "BudgetLine",
    "BudgetReport",
    "Category",
    "CategoryTotal",
    "ConflictError",
    "CostMethod",
    "ExchangeRate",
    "ExternalSplit",
    "Holding",
    "ImportSummary",
    "NetWorth",
    "NotFoundError",
    "Period",
    "PeriodSummary",
    "PicciuliError",
    "Price",
    "PriceProviderError",
    "PriceUpdate",
    "Register",
    "RegisterEntry",
    "SchemaVersionError",
    "Security",
    "SecurityKind",
    "Settings",
    "Split",
    "Trade",
    "TradeKind",
    "Transaction",
    "TransactionKind",
    "Unset",
    "ValidationError",
    "__version__",
]
