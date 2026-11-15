from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, inspect, text

from picciuli import (
    AccountSplit,
    AccountType,
    Book,
    ConflictError,
    CostMethod,
    ExternalSplit,
    SchemaVersionError,
    ValidationError,
)
from picciuli._db.schema import file_engine, prepare_schema
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import AccountRow

from .conftest import d
from .schema_v1 import SCHEMA_V1


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


def test_each_call_is_atomic(book: Book) -> None:
    checking = book.accounts.create("Checking", AccountType.CHECKING)
    with pytest.raises(ValidationError):
        book.accounts.update(checking.id, name="Renamed", goal="x")  # type: ignore[arg-type]
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
