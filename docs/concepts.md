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

## Investments

An **investment account** can hold shares of **securities** (stocks, ETFs,
funds...) as well as cash. Its ledger and its market value are kept apart:

```
ledger balance  = uninvested cash + cost of the shares held
market value    = uninvested cash + Σ quantity × latest price × exchange rate
unrealized gain = market value − ledger balance
```

The ledger only records **money that moved**, so it stays exact and balanced.
Price changes are **not** transactions: the market value is computed on demand
from the quantities held and the stored prices.

### Buying

An account split on an investment account can carry a security and a
**quantity** (an exact decimal number of shares, up to 8 decimal places).
Buying 1 share for 35 € from your checking account is a transfer that also
moves the share:

| Account splits                            | External splits      |
|-------------------------------------------|----------------------|
| checking −35, investment +35 (+1 share)   | *(none: transfer)*   |
| …with a 1 € fee: checking −36             | −1 Fees              |

[`record_buy`][picciuli.services.InvestmentService.record_buy] builds these
splits. The amount of the share split is its **cost basis**. A fee is recorded
as an expense; add it to the cost instead if you want it in the cost basis.
The money can also come from the cash already in the investment account.

### Prices change

When the price moves to 37.20 €, nothing is written to the ledger. The
[valuation][picciuli.services.InvestmentService.valuation] reports a market
value of 37.20 € and an unrealized gain of 2.20 €. The balance of the account
is still 35 €.

Prices are stored at most **once per security and day**, and
[exchange rates](#currencies) once per currency and day. A valuation on a day
uses the latest price and rate known on or before that day. A holding without a
price counts at cost and is flagged.

### Selling

Selling removes the shares at their cost and records the **realized gain** as
external income (or a loss as an expense). Selling that share for 40 € gives:

| Account splits                             | External splits          |
|--------------------------------------------|--------------------------|
| investment −35 (−1 share), checking +40    | +5 Capital gains         |

[`record_sell`][picciuli.services.InvestmentService.record_sell] computes the
cost of the shares sold with the book's **cost method**, chosen in the settings:

- **Weighted average cost** (default): every share costs the average of the
  shares held. This is how the Italian *regime amministrato* works.
- **FIFO**: the oldest shares are sold first.

Selling every share removes the whole remaining cost, so nothing is left
behind. Fees and taxes withheld on a sale are deducted from the money received
and recorded as expenses. A recorded sale keeps its amounts: changing the cost
method or editing an earlier purchase does not rewrite it.

Other events are ordinary transactions. A **dividend** is income into the
investment (or checking) account. A **stock split** or bonus shares is a single
share split with a zero amount, for example `investment 0 (+9 shares)`.
Quantities can never become negative, and an account can only be closed once
it holds no shares and its balance is zero.

### Currencies

Each security is quoted in a currency (an ISO code such as `USD`). The book's
**currency code** (for example `EUR`) is set in the settings. A security quoted
in another currency is converted with the **exchange rate**: the value of one
unit of that currency in the book currency. Changing the book currency code
deletes the stored rates, because they would no longer be relative to the book
currency.

Rates come from an [exchange-rate provider](api/rates.md), chosen in the
settings independently of the price provider. The built-in one reads Yahoo
Finance currency pairs (free, no API key, updated during the day). Rates are
stored at most once per currency and day, like prices.

### Price providers

A [price provider](api/prices.md) downloads quotes. The book settings select
which one [`refresh_prices`][picciuli.services.InvestmentService.refresh_prices]
uses. Each refresh stores the latest quote as the price of its trading day,
replacing the earlier quote of that day. It also stores, through the
exchange-rate provider, the rates the securities need. It can download the
daily history too. Refreshing every minute
therefore keeps one price per day that follows the market, and a user interface
can show values that move during the day without filling the database.

The built-in provider is **Yahoo Finance**. It is free and needs no API key. It
covers the US exchanges and most European ones: `AAPL`, `VWCE.DE` (XETRA),
`SWDA.MI` (Borsa Italiana), `VUSA.L` (London), `IWDA.AS` (Amsterdam). It also
covers currency pairs. Its endpoints are unofficial: they may change or be rate
limited.

!!! note "Securities bought on gettex"
    gettex (Munich) offers no free price service, and Yahoo Finance has no gettex
    listing. Prices on gettex follow the main exchanges closely, so give an ETF
    bought there the symbol of another listing of the same ISIN. XETRA (`.DE`)
    is usually the best match, for example `VWCE.DE` for IE00BK5BQT80. The
    symbol only tells the library where to read prices; it does not change your
    transactions.

## Settings

The book stores a currency symbol and its number of minor digits. They tell user
interfaces how to display amounts; they never change stored values. It also
stores the ISO currency code, the cost method for sales and the selected price
provider (see [Investments](#investments)).
