# Picciuli

Picciuli is a terminal-based personal finance tracker. It organizes cash-flow
items into categories and periods, calculates category and total balances, and
tracks budgets against spending.

## Features

- Create, edit, and delete cash-flow items with a date, amount, description, and
  category.
- Track loans with manually entered payments and new borrowing. Loan-linked
  expenses record the total amount and signed principal change separately;
  interest is derived from their difference.
- Track savings targets with deposits and withdrawals linked to cash-flow
  items, and see the net accrued savings against each target.
- Use top-level categories and one level of subcategories; choose a symbol and
  display order for each category.
- Create overlapping periods and view a period's balances for any selected
  day. Use `<` and `>` to switch between periods covering that day.
- Assign budgets to categories for a period. Parent category balances and
  budgets include their subcategories.
- Generate a period report with categorized transactions, subtotals, budget
  status, and a selectable cumulative-balance graph.
- Export the report as Markdown and PNG, and optionally convert it to PDF.

## Requirements

- Python 3.10 or later
- A terminal that supports keyboard input and ANSI colors

## Install and run

From the project directory:

```bash
python3 -m venv .env
source .env/bin/activate
python -m pip install -r requirements.txt
python main.py finance.db
```

The database is created at the path passed to the application. Keep using the
same path to reopen your data.

To create a separate example database showcasing categories, periods, budgets,
reports, loan repayments, and savings contributions, run:

```bash
python main.py --demo demo.db
python main.py demo.db
```

The demo command creates a new file and will not overwrite an existing one.

## Using the application

The overview shows the selected month's calendar, cash-flow items for the
selected day, and balances for the selected period. An asterisk (`*`) in the
calendar marks a day with one or more cash-flow items. Key bindings are shown
in labeled groups at the bottom of each screen.

On the overview:

- Use the arrow keys to move by day or week, and `[` / `]` to move by month.
- Press `a` to add a cash-flow item. Use positive amounts for income and
  negative amounts for expenses.
- Use `j` / `k` to select a day's item, `e` to edit it, and `d` to delete it.
- Press `n` to create a period starting on the selected day, or `r` to rename
  the period. If periods overlap on the selected day, press `<` / `>` to switch
  the balance panel between them.
- Press `c` to add a category; `m` opens category management. In that screen,
  use the arrow keys to select, `e` to edit, `d` to delete, `c` to add a
  top-level category, `s` to add a subcategory, and `j` / `k` to reorder
  categories within their group.
- When adding a cash-flow item, choose a loan to record a repayment or new
  borrowing; enter the expense amount and principal change separately. Use a
  positive principal change for repayment and a negative one for new borrowing.
- Press `l` to add loans and review each loan's remaining principal, interest
  paid, and payment history (newest first). Repayments and new borrowing are
  entered manually; automatic payments and interest calculations are not
  managed. Use the
  up/down arrows to select a loan and `j` / `k` to scroll its payment history.
- Press `t` to add savings targets and review progress and transactions.
  When adding a cash-flow item, choose a savings target and enter a positive
  amount for a deposit or a negative amount for a withdrawal. Deposits are
  recorded as expenses and withdrawals as income in the selected category.
  Use the up/down arrows to select a target and `j` / `k` to scroll its history.
- The overview separately displays outstanding loan principal and total
  savings accrued. These values are not combined into a net-worth figure.
- Press `p` to manage periods, `b` to manage budgets, `u` to change the
  currency, or `v` to open a report for the selected period. Period reports
  include loans with principal remaining.
- Press `q` to quit.

In the report screen, use `g` to choose which category lines appear in the
graph and `s` to save the Markdown report and PNG graph under `reports/`.
The total graph line always includes all categories.

## Create a PDF report (optional)

The PDF helper uses Pandoc and XeLaTeX. On Debian or Ubuntu, install them with:

```bash
sudo apt install pandoc texlive-xetex fonts-dejavu-core
```

Convert a saved report (the graph is resolved relative to the Markdown file):

```bash
scripts/report-to-pdf.sh reports/period-1-Example.md
```

By default, the PDF is written beside the Markdown file with the same base
name. An optional second argument specifies another output path:

```bash
scripts/report-to-pdf.sh reports/period-1-Example.md ~/Documents/period.pdf
```

## Tests

With the project environment active, run:

```bash
python -m unittest
```
