"""Convert a legacy Picciuli v1 database into the v2 library format.

Usage:
    python tools/migrate_v1.py OLD.db NEW.db [--main-account NAME]

The old file is only read. The new file must not exist; it is deleted again if
the conversion fails. Mapping rules (see docs/migration.md):

* currency, categories (tree, symbols, order), periods and budgets are copied;
  datetimes become dates;
* every old cash flow becomes a transaction on a single checking account
  ("Main" by default);
* each loan becomes a LOAN account with opening balance -amount;
  a repayment (principal p >= 0, total a < 0) becomes
  Main a / loan +p / external a+p (the interest) in the original category;
  new borrowing (p < 0) is a financed purchase:
  Main a-p / loan p / external a in the original category;
* each savings target becomes a SAVINGS account whose goal is the target;
  contributions become transfers between Main and that account (transfers have
  no category, so the original category is dropped and reported).

After the conversion the balances are checked against the old totals.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from picciuli import (
    AccountSplit,
    AccountType,
    Book,
    ExternalSplit,
    PicciuliError,
    Split,
    ValidationError,
)


class MigrationError(Exception):
    """The old database cannot be converted consistently."""


@dataclass
class Report:
    categories: int = 0
    periods: int = 0
    budgets: int = 0
    transactions: int = 0
    loans: int = 0
    savings: int = 0
    warnings: list[str] = field(default_factory=list)

    def lines(self) -> Iterator[str]:
        yield (
            f"Migrated {self.categories} categories, {self.periods} periods, "
            f"{self.budgets} budgets, {self.transactions} transactions, "
            f"{self.loans} loan accounts, {self.savings} savings accounts."
        )
        for warning in self.warnings:
            yield f"warning: {warning}"


def _day(value: Any) -> dt.date:
    return dt.date.fromisoformat(str(value)[:10])


def _unique(name: str, used: set[str]) -> str:
    candidate, index = name, 2
    while candidate.casefold() in used:
        candidate = f"{name} ({index})"
        index += 1
    used.add(candidate.casefold())
    return candidate


class _Old:
    def __init__(self, connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        self.connection = connection
        self.tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {"categories", "cash_flows", "periods"} <= self.tables:
            raise MigrationError("not a Picciuli v1 database")

    def columns(self, table: str) -> set[str]:
        return {
            row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")
        }

    def rows(self, table: str, order: str = "id") -> list[sqlite3.Row]:
        if table not in self.tables:
            return []
        return self.connection.execute(
            f"SELECT * FROM {table} ORDER BY {order}"
        ).fetchall()


def migrate(old_path: Path, new_path: Path, *, main_account: str = "Main") -> Report:
    """Convert `old_path` into a new database at `new_path`."""
    if new_path.exists():
        raise MigrationError(f"{new_path} already exists")
    if not old_path.is_file():
        raise MigrationError(f"{old_path} not found")
    uri = old_path.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            old = _Old(connection)
            with Book.open(new_path) as book, book.atomic():
                report = _convert(old, book, main_account)
    except BaseException:
        new_path.unlink(missing_ok=True)
        raise
    return report


def _convert(old: _Old, book: Book, main_account: str) -> Report:
    report = Report()
    cash_columns = old.columns("cash_flows")

    settings = old.rows("settings")
    if settings and settings[0]["currency"]:
        book.settings.update(currency=settings[0]["currency"])

    # Categories: parents first, then children, each in their old order.
    category_ids: dict[int, int] = {}
    used_names: set[str] = set()
    categories = old.rows("categories", "parent_id IS NOT NULL, sort_order, id")
    for row in categories:
        name = _unique(row["name"].strip() or f"Category {row['id']}", used_names)
        if name != row["name"]:
            report.warnings.append(f"category {row['name']!r} renamed to {name!r}")
        parent = category_ids[row["parent_id"]] if row["parent_id"] else None
        try:
            created = book.categories.create(
                name, parent_id=parent, symbol=row["symbol"]
            )
        except ValidationError:
            created = book.categories.create(name, parent_id=parent)
        category_ids[row["id"]] = created.id
    report.categories = len(category_ids)

    # Periods: create with explicit ends, then reopen the open-ended ones, so
    # that the automatic closing of open periods does not alter the old data.
    period_ids: dict[int, int] = {}
    reopen: list[int] = []
    for row in old.rows("periods", "start_date, id"):
        start = _day(row["start_date"])
        end = _day(row["end_date"]) if row["end_date"] else start
        period = book.periods.create(
            start, end=end, name=(row["name"] or "").strip() or None
        )
        period_ids[row["id"]] = period.id
        if not row["end_date"]:
            reopen.append(period.id)
    for period_id in reopen:
        book.periods.update(period_id, end=None)
    report.periods = len(period_ids)

    for row in old.rows("budgets"):
        book.budgets.create(
            category_ids[row["category_id"]],
            period_ids[row["period_id"]],
            row["amount"],
        )
        report.budgets += 1

    account_names: set[str] = set()
    main = book.accounts.create(
        _unique(main_account, account_names), AccountType.CHECKING
    )
    loan_ids: dict[int, int] = {}
    loan_amounts: dict[int, int] = {}
    for row in old.rows("loans"):
        account = book.accounts.create(
            _unique(row["name"], account_names),
            AccountType.LOAN,
            opening_balance=-row["amount"],
        )
        loan_ids[row["id"]] = account.id
        loan_amounts[row["id"]] = row["amount"]
    savings_ids: dict[int, int] = {}
    for row in old.rows("savings_targets"):
        account = book.accounts.create(
            _unique(row["name"], account_names), AccountType.SAVINGS, goal=row["amount"]
        )
        savings_ids[row["id"]] = account.id
    report.loans, report.savings = len(loan_ids), len(savings_ids)

    old_total = 0
    borrowed = 0
    principal_paid = dict.fromkeys(loan_ids, 0)
    accrued = dict.fromkeys(savings_ids, 0)
    dropped_categories = 0
    for row in old.rows("cash_flows", "occurred_at, id"):
        amount: int = row["amount"]
        category = category_ids[row["category_id"]]
        loan = row["loan_id"] if "loan_id" in cash_columns else None
        target = (
            row["savings_target_id"] if "savings_target_id" in cash_columns else None
        )
        splits: list[Split]
        if loan is not None:
            principal: int = row["principal_amount"] or 0
            principal_paid[loan] += principal
            if principal >= 0:
                main_amount, external = amount, amount + principal
            else:
                main_amount, external = amount - principal, amount
                borrowed += principal
            splits = []
            if main_amount:
                splits.append(AccountSplit(main.id, main_amount))
            if principal:
                splits.append(AccountSplit(loan_ids[loan], principal))
            if external:
                splits.append(ExternalSplit(external, category))
        elif target is not None:
            accrued[target] -= amount
            dropped_categories += 1
            splits = [
                AccountSplit(main.id, amount),
                AccountSplit(savings_ids[target], -amount),
            ]
        else:
            splits = [AccountSplit(main.id, amount), ExternalSplit(amount, category)]
        old_total += amount
        if not splits:
            report.warnings.append(f"cash flow {row['id']} has a zero amount; skipped")
            continue
        book.transactions.create(
            _day(row["occurred_at"]), splits, description=row["description"]
        )
        report.transactions += 1
    if dropped_categories:
        report.warnings.append(
            f"{dropped_categories} savings contribution(s) became uncategorized "
            "transfers; budgets on their old categories may show less spending"
        )
    if borrowed:
        report.warnings.append(
            f"new borrowing of {-borrowed} (minor units) was treated as financed "
            "purchases: the Main account no longer pays for it"
        )

    _verify(
        book,
        main.id,
        old_total - borrowed,
        loan_ids,
        loan_amounts,
        principal_paid,
        savings_ids,
        accrued,
    )
    return report


def _verify(
    book: Book,
    main_id: int,
    expected_main: int,
    loan_ids: dict[int, int],
    loan_amounts: dict[int, int],
    principal_paid: dict[int, int],
    savings_ids: dict[int, int],
    accrued: dict[int, int],
) -> None:
    problems = []
    if book.accounts.balance(main_id) != expected_main:
        problems.append(
            f"main balance {book.accounts.balance(main_id)} != expected {expected_main}"
        )
    for old_id, new_id in loan_ids.items():
        expected = -(loan_amounts[old_id] - principal_paid[old_id])
        if book.accounts.balance(new_id) != expected:
            problems.append(f"loan {old_id} balance mismatch")
    for old_id, new_id in savings_ids.items():
        if book.accounts.balance(new_id) != accrued[old_id]:
            problems.append(f"savings target {old_id} balance mismatch")
    if problems:
        raise MigrationError("; ".join(problems))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old", type=Path, help="legacy v1 database (read only)")
    parser.add_argument("new", type=Path, help="new database to create")
    parser.add_argument(
        "--main-account", default="Main", help="name of the main account"
    )
    args = parser.parse_args(argv)
    try:
        report = migrate(args.old, args.new, main_account=args.main_account)
    except (MigrationError, PicciuliError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for line in report.lines():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
