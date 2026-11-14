# picciuli

Core engine of Picciuli, a personal budgeting and money tracking library.

It manages multiple accounts (checking, savings, credit cards, loans, mortgages and
more), balanced split transactions, optionally categorized external cash flows,
user-defined periods and per-category budgets. All data is stored in a single
SQLite file.

```python
import datetime as dt
from picciuli import AccountType, Book

with Book.open("finance.db") as book:
    checking = book.accounts.create("Checking", AccountType.CHECKING)
    food = book.categories.create("Food")
    book.transactions.record_expense(
        dt.date(2025, 1, 3), 4250, account_id=checking.id, category_id=food.id
    )
    print(book.accounts.balance(checking.id))  # -4250 (minor units)
```

See the project documentation for concepts and the full API reference.
