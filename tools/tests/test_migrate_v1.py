from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from migrate_v1 import MigrationError, main, migrate
from picciuli import AccountType, Book, ExternalSplit, TransactionKind

V1_SCHEMA = """
CREATE TABLE settings (id INTEGER PRIMARY KEY, currency VARCHAR NOT NULL);
CREATE TABLE categories (
    id INTEGER PRIMARY KEY, name VARCHAR NOT NULL UNIQUE, symbol VARCHAR(12) NOT NULL,
    sort_order INTEGER NOT NULL, parent_id INTEGER REFERENCES categories(id));
CREATE TABLE loans (
    id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, amount INTEGER NOT NULL);
CREATE TABLE savings_targets (
    id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, amount INTEGER NOT NULL);
CREATE TABLE cash_flows (
    id INTEGER PRIMARY KEY, amount INTEGER NOT NULL, description VARCHAR,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    occurred_at DATETIME NOT NULL,
    loan_id INTEGER REFERENCES loans(id), principal_amount INTEGER,
    savings_target_id INTEGER REFERENCES savings_targets(id));
CREATE TABLE periods (
    id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, start_date DATETIME NOT NULL,
    end_date DATETIME);
CREATE TABLE budgets (
    id INTEGER PRIMARY KEY, amount INTEGER NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    period_id INTEGER NOT NULL REFERENCES periods(id));
"""

V1_DATA = """
INSERT INTO settings VALUES (1, '€');
INSERT INTO categories VALUES (1, 'Home', 'HOME', 2, NULL);
INSERT INTO categories VALUES (2, 'Food', 'FOOD', 1, NULL);
INSERT INTO categories VALUES (3, 'Rent', 'RENT', 1, 1);
INSERT INTO categories VALUES (4, 'food', 'F2', 3, NULL);
INSERT INTO loans VALUES (1, 'Car loan', 100000);
INSERT INTO loans VALUES (2, 'Main', 5000);
INSERT INTO savings_targets VALUES (1, 'Holiday', 50000);
INSERT INTO periods VALUES (1, 'January', '2024-01-01 00:00:00.000000',
    '2024-01-31 23:59:59.999999');
INSERT INTO periods VALUES (2, 'February', '2024-02-01 00:00:00.000000', NULL);
INSERT INTO periods VALUES (3, 'Trip', '2024-01-10 00:00:00.000000',
    '2024-01-12 00:00:00.000000');
INSERT INTO budgets VALUES (1, 30000, 2, 1);
INSERT INTO budgets VALUES (2, 80000, 1, 2);
INSERT INTO cash_flows VALUES (1, 300000, 'Salary', 1, '2024-01-01 09:00:00.000000',
    NULL, NULL, NULL);
INSERT INTO cash_flows VALUES (2, -4500, 'Market', 2, '2024-01-03 10:00:00.000000',
    NULL, NULL, NULL);
INSERT INTO cash_flows VALUES (3, -12000, 'Car instalment', 1,
    '2024-01-15 00:00:00.000000', 1, 10000, NULL);
INSERT INTO cash_flows VALUES (4, -10500, 'Bike on credit', 1,
    '2024-01-20 00:00:00.000000', 2, -10000, NULL);
INSERT INTO cash_flows VALUES (5, -20000, 'To holiday fund', 2,
    '2024-02-01 00:00:00.000000', NULL, NULL, 1);
INSERT INTO cash_flows VALUES (6, 5000, 'From holiday fund', 2,
    '2024-02-05 00:00:00.000000', NULL, NULL, 1);
INSERT INTO cash_flows VALUES (7, -5000, 'Pure principal', 1,
    '2024-02-10 00:00:00.000000', 1, 5000, NULL);
"""


def make_v1(path: Path, data: str = V1_DATA) -> Path:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(V1_SCHEMA + data)
    return path


def test_full_migration(tmp_path: Path) -> None:
    new = tmp_path / "new.db"
    report = migrate(make_v1(tmp_path / "old.db"), new)
    assert (report.categories, report.periods, report.budgets) == (4, 3, 2)
    assert (report.transactions, report.loans, report.savings) == (7, 2, 1)
    assert any("renamed" in w for w in report.warnings)
    assert any("uncategorized transfers" in w for w in report.warnings)
    assert any("financed purchases" in w for w in report.warnings)

    with Book.open(new, create=False) as book:
        assert book.settings.get().currency == "€"
        names = [(c.name, c.symbol, c.position) for c in book.categories.list()]
        assert names == [
            ("Food", "FOOD", 1),
            ("Home", "HOME", 2),
            ("Rent", "RENT", 1),
            ("food (2)", "F2", 3),
        ]
        cats = {c.name: c.id for c in book.categories.list()}

        accounts = {a.name: a for a in book.accounts.list()}
        assert {name: a.type for name, a in accounts.items()} == {
            "Main": AccountType.CHECKING,
            "Car loan": AccountType.LOAN,
            "Main (2)": AccountType.LOAN,
            "Holiday": AccountType.SAVINGS,
        }
        assert accounts["Holiday"].goal == 50000
        balance = book.accounts.balance
        assert balance(accounts["Car loan"].id) == -100000 + 10000 + 5000
        assert balance(accounts["Main (2)"].id) == -5000 - 10000
        assert balance(accounts["Holiday"].id) == 15000
        # The old total, minus the financed 10000 of the bike that Main never paid.
        assert (
            balance(accounts["Main"].id) == 300000 - 4500 - 12000 - 500 - 15000 - 5000
        )

        txs = book.transactions.list()
        assert [t.date for t in txs][:2] == [dt.date(2024, 1, 1), dt.date(2024, 1, 3)]
        instalment = txs[2]
        assert instalment.description == "Car instalment"
        assert instalment.external_splits == (ExternalSplit(-2000, cats["Home"]),)
        bike = txs[3]
        assert bike.external_splits == (ExternalSplit(-10500, cats["Home"]),)
        assert [t.kind for t in txs[4:6]] == [TransactionKind.TRANSFER] * 2
        assert txs[6].external_splits == ()

        periods = {p.name: p for p in book.periods.list()}
        assert (periods["January"].start, periods["January"].end) == (
            dt.date(2024, 1, 1),
            dt.date(2024, 1, 31),
        )
        assert periods["February"].end is None
        assert periods["Trip"].end == dt.date(2024, 1, 12)
        assert {(b.category_id, b.amount) for b in book.budgets.list()} == {
            (cats["Food"], 30000),
            (cats["Home"], 80000),
        }


def test_minimal_old_schema_without_loans_and_savings(tmp_path: Path) -> None:
    old = tmp_path / "old.db"
    with closing(sqlite3.connect(old)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE categories (id INTEGER PRIMARY KEY, name VARCHAR,
                symbol VARCHAR, sort_order INTEGER, parent_id INTEGER);
            CREATE TABLE cash_flows (id INTEGER PRIMARY KEY, amount INTEGER,
                description VARCHAR, category_id INTEGER, occurred_at DATETIME);
            CREATE TABLE periods (id INTEGER PRIMARY KEY, name VARCHAR,
                start_date DATETIME, end_date DATETIME);
            INSERT INTO categories VALUES (1, 'Misc', '', 1, NULL);
            INSERT INTO cash_flows VALUES (1, -100, NULL, 1, '2024-03-01 12:00:00');
            """
        )
    new = tmp_path / "new.db"
    report = migrate(old, new, main_account="Wallet")
    assert report.transactions == 1
    with Book.open(new) as book:
        (account,) = book.accounts.list()
        assert (account.name, book.accounts.balance(account.id)) == ("Wallet", -100)
        assert book.categories.list()[0].symbol == "MISC"


def test_refuses_existing_target_and_cleans_up_on_failure(tmp_path: Path) -> None:
    old = make_v1(tmp_path / "old.db")
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"")
    with pytest.raises(MigrationError, match="already exists"):
        migrate(old, existing)
    with pytest.raises(MigrationError, match="not found"):
        migrate(tmp_path / "missing.db", tmp_path / "x.db")

    foreign = tmp_path / "foreign.db"
    with closing(sqlite3.connect(foreign)) as connection, connection:
        connection.execute("CREATE TABLE other (id INTEGER)")
    target = tmp_path / "new.db"
    with pytest.raises(MigrationError, match="not a Picciuli v1"):
        migrate(foreign, target)
    assert not target.exists()


def test_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    old = make_v1(tmp_path / "old.db")
    assert main([str(old), str(tmp_path / "new.db")]) == 0
    assert "Migrated 4 categories" in capsys.readouterr().out
    assert main([str(old), str(tmp_path / "new.db")]) == 1
    assert "already exists" in capsys.readouterr().err
