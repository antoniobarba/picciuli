# Concepts

## Amounts, signs and dates

- Every amount is an `int` counting **minor units** (cents). Nothing is ever
  stored as a float. Use [`picciuli.money`](api/money.md) to parse and format.
- Signs are **from your point of view**: positive means money coming to you,
  negative means money going away.
- Dates are `datetime.date` values. Every date range is **inclusive** on both
  ends.

## Accounts

An account is a place where money is kept or owed. Its
[type](api/model.md#picciuli.model.AccountType) decides whether it is an
**asset** (checking, savings, cash, investment, other asset) or a **liability**
(credit card, loan, mortgage, other liability).

Liabilities hold **negative** balances while you owe money. A mortgage of
150,000 has a balance of `-15000000`. This is why net worth is simply the sum of
all balances.

Balances are never stored; they are always calculated:

```
balance(day) = opening balance (if opening_date is unset or <= day)
             + sum of the account splits dated on or before day
```

- **Opening date.** When set, no transaction can be dated earlier than it.
- **Goal.** An optional target balance, for example for a savings account.
- **Closing.** A closed account keeps its history but rejects new transactions.
  Its transactions cannot be edited until the account is reopened. An account can
  only be closed when its balance is zero. Accounts that were never used can be
  deleted.

## Transactions and splits

A transaction has a date, a description, notes, and a list of **splits**. There
are two kinds of split:

- An **account split** changes the balance of one of your accounts.
- An **external split** is money crossing the boundary of your accounts: income
  (positive) or expense (negative), with an optional category.

One rule applies to every transaction:

> **The account splits add up to the same total as the external splits.**

Money cannot appear or disappear: what the outside world gives or takes is
exactly what your accounts gain or lose. All the common cases follow from this
rule:

| Situation                      | Account splits                     | External splits                  |
|--------------------------------|------------------------------------|----------------------------------|
| Salary                         | checking +2000                     | +2000 Salary                     |
| Groceries paid by card         | card −50                           | −50 Food                         |
| Paying the card bill           | checking −50, card +50             | *(none: transfer)*               |
| Saving money                   | checking −100, savings +100        | *(none: transfer)*               |
| Receiving a loan               | checking +5000, loan −5000         | *(none: transfer)*               |
| Mortgage instalment            | checking −600, mortgage +450       | −150 Interest                    |
| Supermarket, split receipt     | card −100                          | −60 Food, −40 Home               |
| Bank fee nobody categorized    | checking −2                        | −2 *(uncategorized)*             |

The library offers shortcuts for the most common cases:
[`record_expense`][picciuli.services.TransactionService.record_expense],
[`record_income`][picciuli.services.TransactionService.record_income] and
[`record_transfer`][picciuli.services.TransactionService.record_transfer].

The [`kind`][picciuli.model.Transaction.kind] property classifies a transaction
from its external splits:

- *transfer*: there are no external splits;
- *income*: all external splits are positive;
- *expense*: all external splits are negative;
- *mixed*: there are external splits of both signs.

## Categories

Categories form a two-level tree: top-level categories with optional
subcategories, ordered by position. Category names, like account names, are
unique regardless of case.

A category that is in use cannot simply be deleted: you must say where its
splits go (`reassign_to`, which can also be `None` for uncategorized). Deleting a
category also deletes its budgets.

## Periods

A period is a named range of days, for example a month, a pay cycle or a
holiday. Periods may overlap. An *open-ended* period has no end day. Creating a
new open-ended period closes the earlier open-ended ones on the day before it
starts, so "start next month" naturally ends the current month.

[`summary`][picciuli.services.PeriodService.summary] reports for a period:

- net flow per category, with subcategories rolled up into their parent;
- the uncategorized total;
- total income and total expenses;
- each account's opening and closing balance.

Transfers never count as income or expense.

## Budgets

A budget is a non-negative allowance for one category in one period. A budget
on a top-level category covers its subcategories too. The
[`report`][picciuli.services.BudgetService.report] compares each budget with
the actual net flow:

- `remaining = budget + actual`;
- spending is negative, so overspending makes `remaining` negative;
- the report totals count each flow only once.

Only external flows consume budgets. If you want to plan your savings, give the
savings account a goal instead.

## Settings

The book stores a currency symbol and its number of minor digits. They tell user
interfaces how to display amounts; they never change stored values.
