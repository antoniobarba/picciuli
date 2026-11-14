# Console interface

`picciuli-tui` is a full-screen console interface for Picciuli books, built with
[Textual](https://textual.textualize.io/). It lives in `apps/tui` and uses only
the public API of the library.

## Running it

```bash
pip install -e packages/picciuli -e apps/tui    # or: uv sync

picciuli-tui finance.db          # open a book (the file is created if missing)
picciuli-tui --demo demo.db      # create a demonstration book, then:
picciuli-tui demo.db
```

`python -m picciuli_tui finance.db` works too. The demonstration book contains
five accounts, a category tree, four salary-to-salary pay cycles with budgets,
transfers, a mortgage instalment split into principal and interest, a split
receipt and an overlapping "Holiday" period.

The mouse works everywhere, and `ctrl+p` opens a command palette with every
action. Press `?` at any time for the list of keys.

## Screens

The tabs at the top of the window switch between the five screens: Overview,
Accounts, Categories, Periods and Budgets. Click a tab or press its number,
`1` to `5`. The footer only lists the keys of the current screen.

## Overview

The overview is built around a month calendar where every day is a boxed cell.
The **selected day** has a heavy accent border and a filled background (brighter
while the calendar has the focus). Today's date number is highlighted. The
cells grow with the window.

- Each day shows its **net flow**, the sum of its income and expenses, in a
  compact form such as `-45`, `+2.5k` or `-1.2M`. A `↔` marks days that only
  have transfers between your accounts. On narrow terminals a `•` marks days
  with transactions.
- Weeks start on Monday. The grid always shows six weeks: days of the previous
  and next month are dimmed, and you can select them.
- The **selected period** is drawn as a tinted band, with its first and last day
  stronger. When several periods cover the selected day, `[` and `]` switch
  between them. The title above the grid shows the period's name, its days and
  its position (`[1/2]`).
- The period's income, expenses and net are shown under the grid.

The right side lists the selected day's transactions. Below them come the
period's categories with their actual flow, budget and what is left (top-level
categories include their subcategories), then the balance of every account at
the end of the selected day and the net worth.

| Key | Action |
|-----|--------|
| `←` `→` `↑` `↓` | Previous / next day, previous / next week |
| `pgup` `pgdn`, mouse wheel | Previous / next month |
| click | Select a day; click `‹` or `›` to change month |
| `t` | Today |
| `g` | Go to a date |
| `tab` | Switch between the calendar and the day list |
| `n` | New transaction on the selected day |
| `enter` / `e`, `d` | Edit / delete the selected transaction |
| `[` `]` | Previous / next period covering the day |
| `p` | Start a period on the selected day |

## Transactions

The transaction form has four kinds:

- **Expense** and **Income**: an amount, an account and a category (or
  *Uncategorized*). Amounts are always typed as positive numbers.
- **Transfer**: an amount moving from one of your accounts to another. Use it to
  pay a credit card bill, save money or receive a loan.
- **Split**: any number of lines. Account lines are balance changes (`+` money
  in, `-` money out); the other lines are income (`+`) or expenses (`-`) with
  a category. A live line shows both totals; they must match (see
  [Concepts](concepts.md#transactions-and-splits)). `ctrl+n` adds a line, and
  switching to Split pre-fills the lines from the simple form, with at least
  three lines (one source account and two destinations is the common case).

Editing a transaction opens the simple form when it is a plain expense, income
or transfer, and the split editor otherwise. Transactions of closed accounts
cannot be changed until the account is reopened.

## Other screens

| Key | Screen | What you can do |
|-----|--------|-----------------|
| `1` | Overview | See above |
| `2` | Accounts | Create and edit accounts, reorder them (`shift+↑↓`), close or reopen them (`c`), delete unused ones. `enter` opens the **register**: every transaction of the account with its running balance. |
| `3` | Categories | Edit the two-level tree, reorder it within each group, delete categories. Deleting a category that is in use asks where its transactions should go. |
| `4` | Periods | Create, edit and delete periods. A period without an end is open-ended, and creating one ends the earlier open-ended periods. |
| `5` | Budgets | Budgets of a period (`[` `]` change period) with their progress; `y` copies budgets from another period. |
| `s` | Settings | Currency symbol and number of decimal digits. |

Lists share the same keys: `↑` `↓` (or `j` `k`) to move, `n` to create,
`enter` or `e` to edit and `d` to delete; deleting always asks first.

## Forms

`tab` and `shift+tab` move between fields, `enter` or `ctrl+s` saves and `esc`
cancels. If the library rejects the input, the error is shown and the form stays
open. Dates can be typed as `2025-02-03`, `3/2/2025`, `3/2` (this year), `3`
(this month), `today`, or as offsets such as `+1` and `-7`.
