# Picciuli

Picciuli is a personal budgeting and money tracking engine. It is a Python
library backed by a single SQLite file, designed to be shared by several user
interfaces: web, mobile and desktop.

> **Status:** version 2 is a complete rewrite. This repository contains the
> core library, a web/mobile app built on it, the API server and the
> documentation.
> The original console application is preserved under the git tag
> `v1-legacy`; its databases are not compatible with version 2.

## Features

- Multiple accounts: checking, savings, cash, investment, credit card, loan,
  mortgage and others. Each account has an opening balance and can be closed
  when no longer used.
- Savings goals: several per account, each with a target, a saved amount
  assigned by hand, an optional date, a priority and the monthly amount needed
  to reach it on time.
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

## API server

```bash
pip install -e "apps/api[dev]"   # Python 3.11+
picciuli-api                     # Swagger UI at http://127.0.0.1:8000/docs
```

A multi-user REST API (FastAPI) for web and mobile front-ends: every user gets
a private book, and logins are handled by an OpenID Connect provider (Zitadel).
See [docs/api-server.md](docs/api-server.md) and, to put it online with
automatic deployments, [docs/deployment.md](docs/deployment.md).

## Web and mobile app

```bash
cd apps/web && npm ci && npm run dev    # http://localhost:5173
```

A React Progressive Web App on the API: it runs in any browser and installs on
computers and phones. See [docs/web.md](docs/web.md).

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
