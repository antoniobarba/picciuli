from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from picciuli import (
    AccountType,
    Book,
    ConflictError,
    SchemaVersionError,
    ValidationError,
)
from picciuli._db.schema import file_engine, prepare_schema
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import AccountRow

from .conftest import d


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
    with pytest.raises(SchemaVersionError, match="migrate_v1"):
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

    prepare_schema(engine, target_version=3, migrations={1: step(1), 2: step(2)})
    assert calls == [1, 2]
    with engine.connect() as connection:
        version = connection.scalar(
            text("SELECT value FROM meta WHERE key = 'schema_version'")
        )
    assert version == "3"
    engine.dispose()


def test_failed_upgrade_is_rolled_back(tmp_path: Path) -> None:
    path = tmp_path / "book.db"
    engine = file_engine(path)
    prepare_schema(engine)

    def create_table(connection: Connection) -> None:
        connection.execute(text("CREATE TABLE extra (id INTEGER)"))

    with pytest.raises(SchemaVersionError, match="no migration from schema version 2"):
        prepare_schema(engine, target_version=3, migrations={1: create_table})
    with engine.connect() as connection:
        tables = connection.scalars(
            text("SELECT name FROM sqlite_master WHERE name = 'extra'")
        ).all()
        version = connection.scalar(
            text("SELECT value FROM meta WHERE key = 'schema_version'")
        )
    assert tables == []
    assert version == "1"
    engine.dispose()


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
