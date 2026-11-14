# Getting started

## Install

From a clone of the repository:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e "packages/picciuli[dev,docs]"
```

If you use [uv](https://docs.astral.sh/uv/), `uv sync` at the repository root
does the same for every package in the workspace.

## A first session

```python
import datetime as dt

from picciuli import AccountSplit, AccountType, Book, ExternalSplit
from picciuli.money import format_amount, parse_amount

with Book.open("finance.db") as book:
    book.settings.update(currency="€")

    checking = book.accounts.create(
        "Checking", AccountType.CHECKING, opening_balance=parse_amount("1500")
    )
    card = book.accounts.create("Visa", AccountType.CREDIT_CARD)
    mortgage = book.accounts.create(
        "Mortgage", AccountType.MORTGAGE, opening_balance=-parse_amount("150000")
    )

    food = book.categories.create("Food")
    interest = book.categories.create("Interest")
    salary = book.categories.create("Salary")

    day = dt.date(2025, 1, 31)
    book.transactions.record_income(
        day, 250000, account_id=checking.id, category_id=salary.id, description="ACME"
    )
    book.transactions.record_expense(
        day, 4250, account_id=card.id, category_id=food.id, description="Market"
    )
    book.transactions.record_transfer(
        day,
        4250,
        from_account_id=checking.id,
        to_account_id=card.id,
        description="Card bill",
    )

    # A mortgage payment: 600 leaves checking, 450 reduces the debt, 150 is interest.
    book.transactions.create(
        day,
        [
            AccountSplit(checking.id, -60000),
            AccountSplit(mortgage.id, 45000),
            ExternalSplit(-15000, interest.id),
        ],
        description="Mortgage instalment",
    )

    for item in book.accounts.balances():
        print(f"{item.account.name:10} {format_amount(item.balance, currency='€')}")
    print(
        "Net worth:", format_amount(book.accounts.net_worth().net_worth, currency="€")
    )
```

## Periods and budgets

```python
january = book.periods.create(dt.date(2025, 1, 1))  # open-ended, named "January 2025"
book.budgets.create(food.id, january.id, parse_amount("400"))

summary = book.periods.summary(january.id)
print(summary.income, summary.expenses, summary.uncategorized)

for line in book.budgets.report(january.id).lines:
    print(line.category.name, line.budget.amount, line.actual, line.remaining)

february = book.periods.create(dt.date(2025, 2, 1))  # closes January on the 31st
book.budgets.copy(january.id, february.id)
```

## Grouping operations

Each method call is its own database transaction. To make several calls succeed
or fail together, use [`Book.atomic`][picciuli.Book.atomic]:

```python
with book.atomic():
    savings = book.accounts.create("Savings", AccountType.SAVINGS, goal=500000)
    book.transactions.record_transfer(
        day, 100000, from_account_id=checking.id, to_account_id=savings.id
    )
```

## Errors

All errors derive from [`PicciuliError`][picciuli.errors.PicciuliError]:
`ValidationError` (bad input), `NotFoundError` (unknown id), `ConflictError`
(conflicts with stored data, such as a duplicate name or a closed account) and
`SchemaVersionError` (the file cannot be used).
