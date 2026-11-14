"""The [`Book`][picciuli.Book] facade: entry point to a Picciuli database."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType

from sqlalchemy import Engine

from picciuli._db.schema import (
    SCHEMA_VERSION,
    file_engine,
    memory_engine,
    prepare_schema,
)
from picciuli._db.session import UnitOfWork
from picciuli.services import (
    AccountService,
    BudgetService,
    CategoryService,
    PeriodService,
    SettingsService,
    TransactionService,
)

__all__ = ["Book"]


class Book:
    """A set of books (accounts, transactions, budgets...) stored in one SQLite file.

    Create it with [`Book.open`][picciuli.Book.open] or
    [`Book.in_memory`][picciuli.Book.in_memory] and use it as a context manager,
    or call [`close`][picciuli.Book.close] when done.

    Every service method runs in its own database transaction. Group several
    calls into one all-or-nothing unit with [`atomic`][picciuli.Book.atomic].

    A `Book` can be shared between threads; each thread gets its own database
    session.

    Example:
        ```python
        with Book.open("finance.db") as book:
            for item in book.accounts.balances():
                print(item.account.name, item.balance)
        ```
    """

    SCHEMA_VERSION = SCHEMA_VERSION
    """Database schema version written by this library release."""

    accounts: AccountService
    """Accounts, balances, registers and net worth."""
    categories: CategoryService
    """The category tree."""
    transactions: TransactionService
    """Recording, editing and searching transactions."""
    periods: PeriodService
    """Periods and period summaries."""
    budgets: BudgetService
    """Budgets and budget reports."""
    settings: SettingsService
    """Book-wide settings such as the currency."""

    def __init__(self, engine: Engine) -> None:
        """Wrap an already prepared engine. Prefer `open` or `in_memory`."""
        self._engine = engine
        self._uow = UnitOfWork(engine)
        self.accounts = AccountService(self._uow)
        self.categories = CategoryService(self._uow)
        self.transactions = TransactionService(self._uow)
        self.periods = PeriodService(self._uow)
        self.budgets = BudgetService(self._uow)
        self.settings = SettingsService(self._uow)

    @classmethod
    def open(cls, path: str | os.PathLike[str], *, create: bool = True) -> Book:
        """Open (and, if needed, create or upgrade) a database file.

        Older schema versions are upgraded in place, in a single transaction.

        Args:
            path: Path of the SQLite file.
            create: Whether to create the file if it does not exist.

        Returns:
            The opened book.

        Raises:
            FileNotFoundError: If the file does not exist and `create` is false.
            SchemaVersionError: If the file is not a Picciuli database or was
                written by a newer library version.
        """
        if not create and not Path(path).exists():
            raise FileNotFoundError(f"database file not found: {os.fspath(path)}")
        engine = file_engine(path)
        try:
            prepare_schema(engine)
        except BaseException:
            engine.dispose()
            raise
        return cls(engine)

    @classmethod
    def in_memory(cls) -> Book:
        """Create a temporary, empty book kept in memory (handy for tests).

        All sessions share a single connection, so an in-memory book must only
        be used from one thread at a time.
        """
        engine = memory_engine()
        prepare_schema(engine)
        return cls(engine)

    @contextlib.contextmanager
    def atomic(self) -> Iterator[None]:
        """Run several service calls in a single database transaction.

        If the block raises, every change made inside it is rolled back. Nested
        `atomic` blocks join the outermost one.

        Example:
            ```python
            with book.atomic():
                savings = book.accounts.create("Savings", AccountType.SAVINGS)
                book.transactions.record_transfer(
                    day, 10000, from_account_id=checking.id, to_account_id=savings.id
                )
            ```
        """
        with self._uow.session():
            yield

    def close(self) -> None:
        """Release the database connections. The book cannot be used afterwards."""
        self._engine.dispose()

    def __enter__(self) -> Book:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
