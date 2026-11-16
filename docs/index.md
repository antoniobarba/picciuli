# Picciuli

Picciuli is a personal budgeting and money tracking engine, written in Python and
storing everything in a single SQLite file.

It is a **library**: it holds all the rules and the data, and has no user
interface of its own. Web, mobile and desktop front-ends are separate programs
built on top of it.

What it handles:

- **Accounts** of any kind: checking, savings, cash, investments, credit cards,
  loans and mortgages. Accounts can have a goal balance, and can be closed when
  you stop using them.
- **Transactions** made of balanced splits. One model covers income, expenses,
  transfers between your accounts, loan payments split into principal and
  interest, and purchases split across several categories.
- **Recurring transactions**: salary, rent, subscriptions or loan payments
  entered once and recorded every day, week, month or year, automatically or
  after you confirm the amount.
- **Categories** in a two-level tree. Any external cash flow can also stay
  uncategorized.
- **Periods**: named date ranges that you define and that may overlap, each
  with a summary of what happened. Monthly periods can start on your payday
  and be created on their own.
- **Budgets** per category and period, with reports comparing them to actual
  spending.
- **Investments**: shares of stocks and ETFs held in investment accounts. The
  ledger records what you paid. Market values come from prices that a
  modular price provider downloads, for example from Yahoo Finance.

Start with [Getting started](getting-started.md), then read
[Concepts](concepts.md) to understand the accounting model. To use Picciuli
in a browser or on a phone, see the [Web and mobile app](web.md).
