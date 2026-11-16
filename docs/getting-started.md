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

Or let the periods follow your payday: each month's period is then created,
with the previous budgets, when you call `ensure_monthly`.

```python
book.settings.update(period_start_day=27)
book.periods.ensure_monthly(dt.date.today())
```

## Recurring transactions

Enter the salary and the mortgage once; `catch_up` records every occurrence
that is due, each on its own day.

```python
from picciuli import ScheduleMode

book.schedules.create(
    dt.date(2025, 2, 27),
    [AccountSplit(checking.id, 250000), ExternalSplit(250000, salary.id)],
    description="ACME",
)
power = book.schedules.create(
    dt.date(2025, 2, 10),
    [AccountSplit(checking.id, -9000), ExternalSplit(-9000)],
    description="Electricity",
    mode=ScheduleMode.CONFIRM,  # the amount changes: wait for confirmation
)

result = book.schedules.catch_up(dt.date(2025, 4, 30))
print(len(result.posted), "recorded,", len(result.due), "to confirm")
book.schedules.post(  # this month's bill, with its real amount
    power.id, splits=[AccountSplit(checking.id, -9137), ExternalSplit(-9137)]
)
```

## Investments

```python
from decimal import Decimal

with Book.open("finance.db") as book:
    book.settings.update(currency_code="EUR", cost_method="average")
    broker = book.accounts.create("Scalable", AccountType.INVESTMENT)
    gains = book.categories.create("Capital gains")
    etf = book.securities.create(
        "Vanguard FTSE All-World",
        currency="EUR",
        kind="etf",
        symbol="VWCE.DE",  # Yahoo Finance symbol (XETRA listing)
        isin="IE00BK5BQT80",
    )

    # 1 share for 35 €, paid from checking: a transfer that also moves the share.
    book.investments.record_buy(
        dt.date(2025, 2, 3),
        account_id=broker.id,
        security_id=etf.id,
        quantity=Decimal("1"),
        cost=3500,
        from_account_id=checking.id,
    )

    # Prices are not transactions: store them by hand or download them.
    book.securities.set_price(etf.id, dt.date(2025, 2, 4), Decimal("37.20"))
    book.investments.refresh_prices()  # latest quotes from Yahoo Finance

    valuation = book.investments.valuation(broker.id)
    print(valuation.balance, valuation.market_value, valuation.unrealized_gain)

    # Selling records the realized gain in a category.
    book.investments.record_sell(
        dt.date(2025, 3, 3),
        account_id=broker.id,
        security_id=etf.id,
        quantity=Decimal("1"),
        proceeds=4000,
        to_account_id=checking.id,
        gain_category_id=gains.id,
    )
    print(book.investments.net_worth().net_worth)  # investments at market value
```

See [Concepts](concepts.md#investments) for the model, and
[Price providers](api/prices.md) and [Exchange-rate providers](api/rates.md)
for the data sources.

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
(conflicts with stored data, such as a duplicate name or a closed account),
`SchemaVersionError` (the file cannot be used) and `PriceProviderError` (a
price provider failed).
