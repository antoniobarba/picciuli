# Picciuli

Picciuli is a personal budgeting and money tracking engine. It is a Python
library backed by a single SQLite file, designed to be shared by several user
interfaces: console, desktop, web and mobile.

> **Status:** version 2 is a complete rewrite. This repository contains the
> core library, a console user interface built on it, and the documentation.
> The original console application is preserved under the git tag
> `v1-legacy`; its databases are not compatible with version 2.

## Features

- Multiple accounts: checking, savings, cash, investment, credit card, loan,
  mortgage and others. Each account has an opening balance and an optional goal,
  and can be closed when no longer used.
- Balanced split transactions, one model for all cases:
  - income and expenses;
  - transfers between your accounts;
  - loan payments split into principal and interest;
  - purchases split across several categories.
- External cash flows can be categorized or left uncategorized.
- A two-level category tree.
- User-defined, possibly overlapping periods, with summaries per period.
- Budgets per category and period that roll up subcategories.
- Investments: securities with exact share quantities, purchases and sales with
  realized gains (weighted average or FIFO cost), market values from stored
  prices and exchange rates, and modular price and exchange-rate providers
  (Yahoo Finance built in, others as plug-ins).
- Net worth and account registers with running balances.
- Typed, documented and fully tested API: frozen dataclasses for results,
  explicit error classes, and all-or-nothing `Book.atomic()` blocks.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -e "packages/picciuli[dev,docs]"
```

```python
import datetime as dt
from picciuli import AccountType, Book

with Book.open("finance.db") as book:
    checking = book.accounts.create("Checking", AccountType.CHECKING)
    food = book.categories.create("Food")
    book.transactions.record_expense(
        dt.date.today(), 4250, account_id=checking.id, category_id=food.id
    )
    print(book.accounts.balance(checking.id))  # -4250 (amounts are in cents)
```

## Console interface

```bash
pip install -e apps/tui
picciuli-tui --demo demo.db      # create a demonstration book
picciuli-tui demo.db             # open it; press ? for the keys
```

A calendar-centred overview shows each day's net flow, the selected period with
its budgets, and your balances. See [docs/tui.md](docs/tui.md).

## API server

```bash
pip install -e "apps/api[dev]"   # Python 3.11+
picciuli-api                     # Swagger UI at http://127.0.0.1:8000/docs
```

A multi-user REST API (FastAPI) for web and mobile front-ends: every user gets
a private book, and logins are handled by an OpenID Connect provider (Zitadel).
See [docs/api-server.md](docs/api-server.md) and, to put it online with
automatic deployments, [docs/deployment.md](docs/deployment.md).

## Documentation

The documentation is generated with MkDocs from the Markdown pages in `docs/`
and the docstrings of the code:

```bash
mkdocs serve          # http://127.0.0.1:8000
```

Recommended reading order:

- [Concepts](docs/concepts.md): the accounting model;
- [Getting started](docs/getting-started.md): practical examples;
- [Development](docs/development.md): repository layout, commands and the
  versioning rules.

## Development

```bash
pytest --cov      # tests and coverage
ruff check .      # lint
mypy              # strict type checking
```

## License

MIT, see [LICENSE](LICENSE).
