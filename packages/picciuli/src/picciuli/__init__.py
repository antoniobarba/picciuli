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
    AccountType,
    Budget,
    BudgetLine,
    BudgetReport,
    Category,
    CategoryTotal,
    ExternalSplit,
    NetWorth,
    Period,
    PeriodSummary,
    Register,
    RegisterEntry,
    Settings,
    Split,
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
    "AccountType",
    "Book",
    "Budget",
    "BudgetLine",
    "BudgetReport",
    "Category",
    "CategoryTotal",
    "ConflictError",
    "ExternalSplit",
    "NetWorth",
    "NotFoundError",
    "Period",
    "PeriodSummary",
    "PicciuliError",
    "Register",
    "RegisterEntry",
    "SchemaVersionError",
    "Settings",
    "Split",
    "Transaction",
    "TransactionKind",
    "Unset",
    "ValidationError",
    "__version__",
]
