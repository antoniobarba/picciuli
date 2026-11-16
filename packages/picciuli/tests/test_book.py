from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, inspect, text

from picciuli import (
    AccountSplit,
    AccountType,
    Book,
    ConflictError,
    CostMethod,
    DebtCharge,
    DebtTerms,
    ExternalSplit,
    GoalPriority,
    SchemaVersionError,
    Trade,
    TradeKind,
    ValidationError,
)
from picciuli._db.schema import file_engine, prepare_schema
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import AccountRow

from .conftest import d
from .schema_v1 import SCHEMA_V1
from .schema_v2 import SCHEMA_V2
from .schema_v3 import SCHEMA_V3
from .schema_v4 import SCHEMA_V4
from .schema_v5 import SCHEMA_V5
from .schema_v6 import SCHEMA_V6


def test_open_creates_and_reopens_a_file(tmp_path: Path) -> None:
    path = tmp_path / "book.db"
    with Book.open(path) as book:
        book.accounts.create("Checking", AccountType.CHECKING)
    with Book.open(path, create=False) as book:
        assert [a.name for a in book.accounts.list()] == ["Checking"]


def test_open_without_create_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Book.open(tmp_path / "missing.db", create=False)
    assert not (tmp_path / "missing.db").exists()


def _set_version(path: Path, value: str) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'", (value,)
        )


def test_open_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "book.db"
    Book.open(path).close()
    _set_version(path, str(Book.SCHEMA_VERSION + 1))
    with pytest.raises(SchemaVersionError, match="newer"):
        Book.open(path)


@pytest.mark.parametrize("value", ["abc", "0"])
def test_open_rejects_invalid_schema_version(tmp_path: Path, value: str) -> None:
    path = tmp_path / "book.db"
    Book.open(path).close()
    _set_version(path, value)
    with pytest.raises(SchemaVersionError, match="invalid"):
        Book.open(path)


def test_open_rejects_legacy_or_foreign_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE cash_flows (id INTEGER PRIMARY KEY)")
    with pytest.raises(SchemaVersionError, match="not a Picciuli database"):
        Book.open(path)


def test_older_schema_is_upgraded_in_order(tmp_path: Path) -> None:
    path = tmp_path / "book.db"
    engine = file_engine(path)
    prepare_schema(engine)
    calls: list[int] = []

    def step(version: int):  # type: ignore[no-untyped-def]
        def run(connection: Connection) -> None:
            calls.append(version)
            connection.execute(text(f"CREATE TABLE extra_{version} (id INTEGER)"))

        return run

    current = Book.SCHEMA_VERSION
    prepare_schema(
        engine,
        target_version=current + 2,
        migrations={current: step(current), current + 1: step(current + 1)},
    )
    assert calls == [current, current + 1]
    with engine.connect() as connection:
        version = connection.scalar(
            text("SELECT value FROM meta WHERE key = 'schema_version'")
        )
    assert version == str(current + 2)
    engine.dispose()


def test_failed_upgrade_is_rolled_back(tmp_path: Path) -> None:
    path = tmp_path / "book.db"
    engine = file_engine(path)
    prepare_schema(engine)
    current = Book.SCHEMA_VERSION

    def create_table(connection: Connection) -> None:
        connection.execute(text("CREATE TABLE extra (id INTEGER)"))

    with pytest.raises(
        SchemaVersionError, match=f"no migration from schema version {current + 1}"
    ):
        prepare_schema(
            engine, target_version=current + 2, migrations={current: create_table}
        )
    with engine.connect() as connection:
        tables = connection.scalars(
            text("SELECT name FROM sqlite_master WHERE name = 'extra'")
        ).all()
        version = connection.scalar(
            text("SELECT value FROM meta WHERE key = 'schema_version'")
        )
    assert tables == []
    assert version == str(current)
    engine.dispose()


def _make_v1(path: Path, currency: str) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(SCHEMA_V1)
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [("schema_version", "1"), ("currency", currency), ("minor_digits", "2")],
        )
        connection.executescript(
            """
            INSERT INTO accounts VALUES (1, 'Checking', 'checking', 0, NULL, NULL,
                NULL, 1, NULL);
            INSERT INTO categories VALUES (1, 'Food', 'Food', NULL, 1);
            INSERT INTO transactions VALUES (1, '2025-01-02', 'Shop', NULL);
            INSERT INTO splits VALUES (1, 1, 1, 1, NULL, -500, 'memo');
            INSERT INTO splits VALUES (2, 1, 2, NULL, 1, -500, NULL);
            """
        )


def _structure(engine: Engine) -> dict[str, object]:
    inspector = inspect(engine)
    result: dict[str, object] = {}
    for table in sorted(inspector.get_table_names()):
        result[table] = (
            [
                (c["name"], str(c["type"]), c["nullable"])
                for c in inspector.get_columns(table)
            ],
            sorted(str(fk) for fk in inspector.get_foreign_keys(table)),
            sorted(
                (c["name"], " ".join(str(c["sqltext"]).split()))
                for c in inspector.get_check_constraints(table)
            ),
            sorted(
                str(u["column_names"]) for u in inspector.get_unique_constraints(table)
            ),
            sorted(
                (i["name"], str(i["column_names"]))
                for i in inspector.get_indexes(table)
            ),
        )
    return result


@pytest.mark.parametrize(
    ("currency", "code"), [("€", "EUR"), ("chf", "CHF"), ("Kč", None)]
)
def test_version_1_is_upgraded_to_version_2(
    tmp_path: Path, currency: str, code: str | None
) -> None:
    path = tmp_path / "v1.db"
    _make_v1(path, currency)
    with Book.open(path) as book:
        settings = book.settings.get()
        assert (settings.currency, settings.currency_code) == (currency, code)
        assert settings.cost_method is CostMethod.AVERAGE
        assert settings.price_provider == "yahoo"
        (tx,) = book.transactions.list()
        assert tx.splits == (AccountSplit(1, -500, "memo"), ExternalSplit(-500, 1))
        broker = book.accounts.create("Broker", AccountType.INVESTMENT)
        etf = book.securities.create("ETF", currency="EUR")
        book.investments.record_buy(
            d(3), account_id=broker.id, security_id=etf.id, quantity=1, cost=100
        )
    fresh = file_engine(tmp_path / "fresh.db")
    prepare_schema(fresh)
    upgraded = file_engine(path)
    try:
        assert _structure(upgraded) == _structure(fresh)
    finally:
        fresh.dispose()
        upgraded.dispose()


def _make_v2(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(SCHEMA_V2)
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", "2"),
                ("currency", "€"),
                ("minor_digits", "2"),
                ("currency_code", "EUR"),
                ("cost_method", "average"),
                ("price_provider", "yahoo"),
            ],
        )
        connection.executescript(
            """
            INSERT INTO accounts VALUES (1, 'Checking', 'checking', 0, NULL, NULL,
                NULL, 1, NULL);
            INSERT INTO accounts VALUES (2, 'Broker', 'investment', 0, NULL, NULL,
                NULL, 2, NULL);
            INSERT INTO categories VALUES (1, 'Gains', 'G', NULL, 1);
            INSERT INTO categories VALUES (2, 'Fees', 'F', NULL, 2);
            INSERT INTO securities VALUES (1, 'ETF', NULL, NULL, 'EUR', 'etf', NULL);
            INSERT INTO transactions VALUES (1, '2025-01-01', 'Buy ETF', NULL);
            INSERT INTO splits VALUES (1, 1, 1, 2, NULL, 1000, NULL, 1, 300000000);
            INSERT INTO splits VALUES (2, 1, 2, 1, NULL, -1010, NULL, NULL, NULL);
            INSERT INTO splits VALUES (3, 1, 3, NULL, 2, -10, 'Fee', NULL, NULL);
            INSERT INTO transactions VALUES (2, '2025-01-02', 'Sell ETF', NULL);
            INSERT INTO splits VALUES (4, 2, 1, 2, NULL, -333, NULL, 1, -100000000);
            INSERT INTO splits VALUES (5, 2, 2, 1, NULL, 490, NULL, NULL, NULL);
            INSERT INTO splits VALUES (6, 2, 3, NULL, 1, 167, 'Realized gain',
                NULL, NULL);
            INSERT INTO splits VALUES (7, 2, 4, NULL, 2, -10, 'Fee', NULL, NULL);
            INSERT INTO transactions VALUES (3, '2025-01-03', 'Vendita', NULL);
            INSERT INTO splits VALUES (8, 3, 1, 2, NULL, -333,
                '1 quote al costo medio', 1, -100000000);
            INSERT INTO splits VALUES (9, 3, 2, 2, NULL, 300, 'incasso vendita',
                NULL, NULL);
            INSERT INTO splits VALUES (10, 3, 3, NULL, 1, -33, 'minusvalenza',
                NULL, NULL);
            INSERT INTO transactions VALUES (4, '2025-01-04', 'Odd', NULL);
            INSERT INTO splits VALUES (11, 4, 1, 2, NULL, 100, NULL, 1, 100000000);
            INSERT INTO splits VALUES (12, 4, 2, 1, NULL, -120, NULL, NULL, NULL);
            INSERT INTO splits VALUES (13, 4, 3, NULL, 2, -10, NULL, NULL, NULL);
            INSERT INTO splits VALUES (14, 4, 4, NULL, 2, -10, NULL, NULL, NULL);
            INSERT INTO transactions VALUES (5, '2025-01-05', 'Shop', NULL);
            INSERT INTO splits VALUES (15, 5, 1, 1, NULL, -50, NULL, NULL, NULL);
            INSERT INTO splits VALUES (16, 5, 2, NULL, 2, -50, NULL, NULL, NULL);
            """
        )


def test_version_2_is_upgraded_with_the_trades_it_can_prove(tmp_path: Path) -> None:
    path = tmp_path / "v2.db"
    _make_v2(path)
    with Book.open(path) as book:
        trades = {t.id: t.trade for t in book.transactions.list()}
        splits = {t.id: t.splits for t in book.transactions.list()}
    assert trades == {
        1: Trade(TradeKind.BUY, 2, 1, Decimal(3), 1000, 1, 10, 2),
        2: Trade(TradeKind.SELL, 2, 1, Decimal(1), 500, 1, 10, 2, gain_category_id=1),
        3: Trade(TradeKind.SELL, 2, 1, Decimal(1), 300, gain_category_id=1),
        4: None,
        5: None,
    }
    assert splits[3][0] == AccountSplit(
        2, -333, "1 quote al costo medio", 1, Decimal(-1)
    )
    fresh = file_engine(tmp_path / "fresh.db")
    prepare_schema(fresh)
    upgraded = file_engine(path)
    try:
        assert _structure(upgraded) == _structure(fresh)
    finally:
        fresh.dispose()
        upgraded.dispose()


def _make_v3(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(SCHEMA_V3)
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", "3"),
                ("currency", "€"),
                ("minor_digits", "2"),
                ("currency_code", "EUR"),
                ("cost_method", "fifo"),
                ("price_provider", "yahoo"),
                ("rate_provider", "yahoo"),
            ],
        )
        connection.executescript(
            """
            INSERT INTO accounts VALUES (1, 'Checking', 'checking', 100000,
                '2025-01-01', 500000, 'main', 1, NULL);
            INSERT INTO accounts VALUES (2, 'Broker', 'investment', 0, NULL, NULL,
                NULL, 2, NULL);
            INSERT INTO accounts VALUES (3, 'Old', 'cash', 0, NULL, NULL, NULL, 3,
                '2025-02-01');
            INSERT INTO categories VALUES (1, 'Food', 'FOOD', NULL, 1);
            INSERT INTO categories VALUES (2, 'Groceries', 'GRO', 1, 1);
            INSERT INTO categories VALUES (3, 'Fees', 'F', NULL, 2);
            INSERT INTO securities VALUES (1, 'ETF', 'VWCE.DE', 'IE00BK5BQT80',
                'EUR', 'etf', 'notes');
            INSERT INTO prices VALUES (1, 1, '2025-01-02', 10000000000, 'yahoo');
            INSERT INTO exchange_rates VALUES (1, 'USD', '2025-01-02', 90000000);
            INSERT INTO periods VALUES (1, 'January 2025', '2025-01-01',
                '2025-01-31');
            INSERT INTO periods VALUES (2, 'February', '2025-02-01', NULL);
            INSERT INTO budgets VALUES (1, 2, 1, 30000);
            INSERT INTO transactions VALUES (1, '2025-01-02', 'Shop', 'note');
            INSERT INTO splits VALUES (1, 1, 1, 1, NULL, -4500, 'memo', NULL, NULL);
            INSERT INTO splits VALUES (2, 1, 2, NULL, 2, -4500, NULL, NULL, NULL);
            INSERT INTO transactions VALUES (2, '2025-01-03', 'Buy ETF', NULL);
            INSERT INTO splits VALUES (3, 2, 1, 2, NULL, 10000, NULL, 1, 100000000);
            INSERT INTO splits VALUES (4, 2, 2, 1, NULL, -10100, NULL, NULL, NULL);
            INSERT INTO splits VALUES (5, 2, 3, NULL, 3, -100, 'Fee', NULL, NULL);
            INSERT INTO trades VALUES (2, 'buy', 2, 1, 100000000, 10000, 1, 100, 3,
                0, NULL, NULL);
            INSERT INTO transactions VALUES (3, '2025-01-05', 'Cash in', NULL);
            INSERT INTO splits VALUES (6, 3, 1, 3, NULL, 700, NULL, NULL, NULL);
            INSERT INTO splits VALUES (7, 3, 2, NULL, NULL, 700, NULL, NULL, NULL);
            INSERT INTO transactions VALUES (4, '2025-01-06', 'Cash out', NULL);
            INSERT INTO splits VALUES (8, 4, 1, 3, NULL, -700, NULL, NULL, NULL);
            INSERT INTO splits VALUES (9, 4, 2, NULL, 1, -700, NULL, NULL, NULL);
            """
        )


def _rows(path: Path) -> dict[str, list[tuple[object, ...]]]:
    with closing(sqlite3.connect(path)) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        return {
            name: connection.execute(
                f'SELECT * FROM "{name}" ORDER BY rowid'
            ).fetchall()
            for (name,) in tables
        }


def _without_goal(accounts: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
    """Account rows of schema version 5 or older, without the `goal` column."""
    return [(*row[:5], *row[6:]) for row in accounts]


def test_version_3_is_upgraded_to_version_4_without_losing_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v3.db"
    _make_v3(path)
    before = _rows(path)

    Book.open(path).close()

    after = _rows(path)
    assert set(after) == set(before) | {
        "schedules",
        "schedule_splits",
        "debt_terms",
        "debt_charges",
        "schedule_debts",
        "savings_goals",
    }
    assert after["schedules"] == after["schedule_splits"] == []
    assert after["debt_terms"] == after["debt_charges"] == after["schedule_debts"] == []
    assert after["savings_goals"] == [(1, 1, "Checking", 500000, 85400, None, "normal")]
    assert after["transactions"] == [(*row, None) for row in before["transactions"]]
    assert after["accounts"] == _without_goal(before["accounts"])
    assert dict(after["meta"]) == {  # type: ignore[arg-type]
        **dict(before["meta"]),  # type: ignore[arg-type]
        "schema_version": "7",
        "period_start_day": "",
        "period_weekend_shift": "1",
    }
    for table in set(before) - {"meta", "transactions", "accounts"}:
        assert after[table] == before[table], table

    fresh = file_engine(tmp_path / "fresh.db")
    prepare_schema(fresh)
    upgraded = file_engine(path)
    try:
        assert _structure(upgraded) == _structure(fresh)
    finally:
        fresh.dispose()
        upgraded.dispose()

    with Book.open(path) as book:
        settings = book.settings.get()
        assert (settings.period_start_day, settings.cost_method) == (
            None,
            CostMethod.FIFO,
        )
        assert book.accounts.balance(1) == 100000 - 4500 - 10100
        assert book.transactions.get(2).trade == Trade(
            TradeKind.BUY, 2, 1, Decimal(1), 10000, 1, 100, 3
        )
        rent = book.schedules.create(
            d(31), [AccountSplit(1, -100), ExternalSplit(-100, 1)]
        )
        (posted,) = book.schedules.catch_up(d(31)).posted
        assert posted.schedule_id == rent.id
    # The upgraded file has exactly the current schema: it can be imported.
    with Book.in_memory() as copy:
        summary = copy.import_file(path)
        assert (summary.transactions, summary.schedules) == (5, 1)
        assert copy.transactions.list()[-1].schedule_id == copy.schedules.list()[0].id


def _make_v4(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(SCHEMA_V4)
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", "4"),
                ("currency", "€"),
                ("minor_digits", "2"),
                ("currency_code", "EUR"),
                ("cost_method", "average"),
                ("price_provider", "yahoo"),
                ("rate_provider", "yahoo"),
                ("period_start_day", "27"),
                ("period_weekend_shift", "1"),
            ],
        )
        connection.executescript(
            """
            INSERT INTO accounts VALUES (1, 'Checking', 'checking', 300000, NULL,
                NULL, NULL, 1, NULL);
            INSERT INTO accounts VALUES (2, 'Visa', 'credit_card', -50000, NULL,
                NULL, 'card', 2, NULL);
            INSERT INTO accounts VALUES (3, 'Mortgage', 'mortgage', -15000000,
                '2024-12-31', NULL, NULL, 3, NULL);
            INSERT INTO categories VALUES (1, 'Food', 'FOOD', NULL, 1);
            INSERT INTO categories VALUES (2, 'Interest', 'INT', NULL, 2);
            INSERT INTO periods VALUES (1, 'January 2025', '2024-12-27',
                '2025-01-26');
            INSERT INTO budgets VALUES (1, 1, 1, 40000);
            INSERT INTO schedules VALUES (1, 'Mortgage', NULL, 'monthly', 1, 5,
                '2025-02-05', NULL, NULL, 'auto', 0, NULL);
            INSERT INTO schedule_splits VALUES (1, 1, 1, 1, NULL, -80000, NULL);
            INSERT INTO schedule_splits VALUES (2, 1, 2, 3, NULL, 60000, NULL);
            INSERT INTO schedule_splits VALUES (3, 1, 3, NULL, 2, -20000, NULL);
            INSERT INTO transactions VALUES (1, '2025-01-05', 'Mortgage', NULL, 1);
            INSERT INTO splits VALUES (1, 1, 1, 1, NULL, -80000, NULL, NULL, NULL);
            INSERT INTO splits VALUES (2, 1, 2, 3, NULL, 60000, NULL, NULL, NULL);
            INSERT INTO splits VALUES (3, 1, 3, NULL, 2, -20000, NULL, NULL, NULL);
            INSERT INTO transactions VALUES (2, '2025-01-10', 'Shop', NULL, NULL);
            INSERT INTO splits VALUES (4, 2, 1, 2, NULL, -4500, NULL, NULL, NULL);
            INSERT INTO splits VALUES (5, 2, 2, NULL, 1, -4500, NULL, NULL, NULL);
            """
        )


def test_version_4_is_upgraded_to_version_5_without_losing_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v4.db"
    _make_v4(path)
    before = _rows(path)

    Book.open(path).close()

    after = _rows(path)
    assert set(after) == set(before) | {
        "debt_terms",
        "debt_charges",
        "schedule_debts",
        "savings_goals",
    }
    assert after["debt_terms"] == after["debt_charges"] == after["schedule_debts"] == []
    assert after["savings_goals"] == []
    assert after["accounts"] == _without_goal(before["accounts"])
    assert dict(after["meta"]) == {  # type: ignore[arg-type]
        **dict(before["meta"]),  # type: ignore[arg-type]
        "schema_version": "7",
    }
    for table in set(before) - {"meta", "accounts"}:
        assert after[table] == before[table], table

    fresh = file_engine(tmp_path / "fresh.db")
    prepare_schema(fresh)
    upgraded = file_engine(path)
    try:
        assert _structure(upgraded) == _structure(fresh)
    finally:
        fresh.dispose()
        upgraded.dispose()

    with Book.open(path) as book:
        assert [a.debt_terms for a in book.accounts.list()] == [None] * 3
        assert book.schedules.get(1).debt is None
        assert book.accounts.balance(3) == -15000000 + 60000
        book.debts.set_terms(
            3, DebtTerms(Decimal(3), payment=80000, interest_category_id=2)
        )
        (status,) = book.debts.list(today=d(31))
        assert status.owed == 14940000
        assert status.payoff is not None
    # The upgraded file has exactly the current schema: it can be imported.
    with Book.in_memory() as copy:
        summary = copy.import_file(path)
        assert (summary.accounts, summary.transactions, summary.schedules) == (3, 2, 1)
        assert copy.accounts.get(3).debt_terms == DebtTerms(
            Decimal(3), payment=80000, interest_category_id=2
        )


def test_version_5_is_upgraded_through_every_step_without_losing_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v5.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(SCHEMA_V5)
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [("schema_version", "5"), ("currency", "€"), ("minor_digits", "2")],
        )
        connection.executescript(
            """
            INSERT INTO accounts VALUES (1, 'Checking', 'checking', 300000, NULL,
                250000, NULL, 1, NULL);
            INSERT INTO accounts VALUES (2, 'Loan', 'loan', -1000000, NULL,
                NULL, NULL, 2, NULL);
            INSERT INTO categories VALUES (1, 'Interest', 'INT', NULL, 1);
            INSERT INTO categories VALUES (2, 'Insurance', 'INS', NULL, 2);
            INSERT INTO debt_terms VALUES (2, 899000000, 13371, NULL, 1, NULL,
                NULL, 1, 1);
            """
        )
    before = _rows(path)

    Book.open(path).close()

    # 5 -> 6 adds the empty `debt_charges`; 6 -> 7 converts the account goal.
    after = _rows(path)
    assert set(after) == set(before) | {"debt_charges", "savings_goals"}
    assert after["debt_charges"] == []
    assert after["savings_goals"] == [
        (1, 1, "Checking", 250000, 250000, None, "normal")
    ]
    assert after["accounts"] == _without_goal(before["accounts"])
    assert ("schema_version", "7") in after["meta"]
    for table in set(before) - {"meta", "accounts"}:
        assert after[table] == before[table], table
    # One backup of the file as it was before the first step.
    assert [p.name for p in tmp_path.glob("*.bak")] == ["v5.db.schema-v5.bak"]
    assert _rows(tmp_path / "v5.db.schema-v5.bak") == before

    fresh = file_engine(tmp_path / "fresh.db")
    prepare_schema(fresh)
    upgraded = file_engine(path)
    try:
        assert _structure(upgraded) == _structure(fresh)
    finally:
        fresh.dispose()
        upgraded.dispose()

    charge = DebtCharge(709, 2, "Insurance")
    with Book.open(path) as book:
        terms = book.accounts.get(2).debt_terms
        assert terms is not None and terms.charges == ()
        book.debts.set_terms(2, replace(terms, charges=(charge,)))
    with Book.in_memory() as copy:
        copy.import_file(path)
        terms = copy.accounts.get(2).debt_terms
        assert terms is not None and terms.charges == (charge,)


def _make_v6(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(SCHEMA_V6)
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", "6"),
                ("currency", "€"),
                ("minor_digits", "2"),
                ("currency_code", "EUR"),
                ("cost_method", "average"),
                ("price_provider", "yahoo"),
                ("rate_provider", "yahoo"),
                ("period_start_day", "1"),
                ("period_weekend_shift", "1"),
            ],
        )
        connection.executescript(
            """
            INSERT INTO accounts VALUES (1, 'Checking', 'checking', 300000, NULL,
                NULL, NULL, 1, NULL);
            INSERT INTO accounts VALUES (2, 'Holiday', 'savings', 50000, NULL,
                100000, 'trip', 2, NULL);
            INSERT INTO accounts VALUES (3, 'Wallet', 'cash', 50000, NULL,
                10000, NULL, 3, NULL);
            INSERT INTO accounts VALUES (4, 'Old box', 'other_asset', 0,
                '2024-01-01', 5000, NULL, 4, '2024-06-30');
            INSERT INTO accounts VALUES (5, 'Broker', 'investment', 0, NULL,
                100000, NULL, 5, NULL);
            INSERT INTO accounts VALUES (6, 'Visa', 'credit_card', 0, NULL,
                -2000, NULL, 6, NULL);
            INSERT INTO accounts VALUES (7, 'Overdrawn', 'checking', -500, NULL,
                1000, NULL, 7, NULL);
            INSERT INTO accounts VALUES (8, 'Later', 'savings', 40000,
                '2999-01-01', 1000, NULL, 8, NULL);
            INSERT INTO accounts VALUES (9, 'Zero', 'savings', 0, NULL, 0, NULL,
                9, NULL);
            INSERT INTO categories VALUES (1, 'Salary', 'PAY', NULL, 1);
            INSERT INTO transactions VALUES (1, '2025-01-05', 'Save', NULL, NULL);
            INSERT INTO splits VALUES (1, 1, 1, 1, NULL, -20000, NULL, NULL, NULL);
            INSERT INTO splits VALUES (2, 1, 2, 2, NULL, 20000, NULL, NULL, NULL);
            INSERT INTO transactions VALUES (2, '2998-12-31', 'Future', NULL, NULL);
            INSERT INTO splits VALUES (3, 2, 1, 2, NULL, 99999, NULL, NULL, NULL);
            INSERT INTO splits VALUES (4, 2, 2, NULL, 1, 99999, NULL, NULL, NULL);
            """
        )


def test_version_6_is_upgraded_to_savings_goals_after_a_backup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v6.db"
    _make_v6(path)
    before = _rows(path)

    with Book.open(path) as book:
        goals = book.goals.list()

    # Eligible positive goals become goals named after their account; the
    # saved amount is today's balance (not future entries), within [0, goal].
    assert [
        (g.account_id, g.name, g.target_amount, g.saved_amount, g.target_date)
        for g in goals
    ] == [
        (2, "Holiday", 100000, 70000, None),
        (3, "Wallet", 10000, 10000, None),
        (4, "Old box", 5000, 0, None),
        (7, "Overdrawn", 1000, 0, None),
        (8, "Later", 1000, 0, None),
    ]
    assert {g.priority for g in goals} == {GoalPriority.NORMAL}
    after = _rows(path)
    assert after["accounts"] == _without_goal(before["accounts"])
    assert ("schema_version", "7") in after["meta"]
    for table in set(before) - {"meta", "accounts"}:
        assert after[table] == before[table], table

    # The backup keeps the file exactly as it was, unsupported goals included.
    backup = tmp_path / "v6.db.schema-v6.bak"
    assert _rows(backup) == before
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]

    fresh = file_engine(tmp_path / "fresh.db")
    prepare_schema(fresh)
    upgraded = file_engine(path)
    try:
        assert _structure(upgraded) == _structure(fresh)
    finally:
        fresh.dispose()
        upgraded.dispose()

    # Opening the upgraded file again neither converts nor backs up again.
    with Book.open(path) as book:
        assert book.goals.list() == goals
    assert sorted(p.name for p in tmp_path.glob("*.bak")) == ["v6.db.schema-v6.bak"]
    with Book.in_memory() as copy:
        assert copy.import_file(path).goals == 5


def test_backup_includes_committed_wal_content(tmp_path: Path) -> None:
    path = tmp_path / "v6.db"
    _make_v6(path)
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        with writer:
            writer.execute(
                "INSERT INTO accounts VALUES (10, 'Late', 'cash', 1, NULL, NULL, "
                "NULL, 10, NULL)"
            )
        assert (tmp_path / "v6.db-wal").stat().st_size > 0
        Book.open(path).close()
    names = [row[1] for row in _rows(tmp_path / "v6.db.schema-v6.bak")["accounts"]]
    assert "Late" in names


def test_backup_never_replaces_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "v6.db"
    _make_v6(path)
    taken = tmp_path / "v6.db.schema-v6.bak"
    taken.write_bytes(b"keep me")

    Book.open(path).close()

    assert taken.read_bytes() == b"keep me"
    assert _rows(tmp_path / "v6.db.schema-v6-2.bak")["accounts"][1][5] == 100000


def test_upgrade_does_not_start_without_a_verified_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "v6.db"
    _make_v6(path)
    before = _rows(path)

    def broken(*_args: object) -> None:
        raise SchemaVersionError("the backup is damaged")

    monkeypatch.setattr("picciuli._db.schema._verify_backup", broken)
    with pytest.raises(SchemaVersionError, match=r"cannot back up.*damaged"):
        Book.open(path)
    assert _rows(path) == before
    assert list(tmp_path.glob("*.bak")) == []


def test_failed_upgrade_keeps_the_backup_and_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from picciuli._db import schema

    path = tmp_path / "v6.db"
    _make_v6(path)
    before = _rows(path)

    def failing(connection: Connection) -> None:
        connection.exec_driver_sql("DELETE FROM accounts WHERE id = 9")
        raise SchemaVersionError("boom")

    monkeypatch.setitem(schema.MIGRATIONS, 6, failing)
    with pytest.raises(SchemaVersionError, match="boom"):
        Book.open(path)
    assert _rows(path) == before
    assert _rows(tmp_path / "v6.db.schema-v6.bak") == before

    monkeypatch.undo()
    with Book.open(path) as book:
        assert len(book.goals.list()) == 5
    assert (tmp_path / "v6.db.schema-v6-2.bak").exists()


def test_in_memory_and_current_books_are_not_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "book.db"
    Book.open(path).close()
    Book.open(path).close()
    assert list(tmp_path.glob("*.bak")) == []


def test_each_call_is_atomic(book: Book) -> None:
    checking = book.accounts.create("Checking", AccountType.CHECKING)
    with pytest.raises(ValidationError):
        book.accounts.update(checking.id, name="Renamed", notes=5)  # type: ignore[arg-type]
    assert book.accounts.get(checking.id).name == "Checking"


def test_atomic_block_rolls_back_everything(book: Book) -> None:
    with pytest.raises(ConflictError), book.atomic():
        book.accounts.create("Checking", AccountType.CHECKING)
        book.categories.create("Food")
        book.accounts.create("checking", AccountType.SAVINGS)
    assert book.accounts.list() == []
    assert book.categories.list() == []


def test_atomic_block_commits_and_nests(book: Book) -> None:
    with book.atomic():
        account = book.accounts.create("Checking", AccountType.CHECKING)
        with book.atomic():
            book.transactions.record_income(d(1), 100, account_id=account.id)
        assert book.accounts.balance(account.id) == 100
    assert book.accounts.balance(account.id) == 100


def test_database_constraint_violations_become_conflicts(book: Book) -> None:
    uow: UnitOfWork = book._uow
    with pytest.raises(ConflictError, match="constraint"), uow.session() as session:
        session.add(AccountRow(name="X", type="bogus", opening_balance=0, position=1))
        session.flush()


def test_book_is_usable_from_several_threads(tmp_path: Path) -> None:
    with Book.open(tmp_path / "book.db") as book:
        account = book.accounts.create("Checking", AccountType.CHECKING)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                for _ in range(5):
                    book.transactions.record_income(d(1), 1, account_id=account.id)
            except BaseException as exc:  # pragma: no cover - only on failure
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert book.accounts.balance(account.id) == 20
