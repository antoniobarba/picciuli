"""The [`Book`][picciuli.Book] facade: entry point to a Picciuli database."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType

from sqlalchemy import Engine

from picciuli._db.merge import import_book
from picciuli._db.schema import (
    SCHEMA_VERSION,
    backup_file,
    file_engine,
    memory_engine,
    prepare_schema,
)
from picciuli._db.session import UnitOfWork
from picciuli._db.upload import Deadline, RawBook, read_file, read_session
from picciuli.errors import PicciuliError, ValidationError
from picciuli.model import ImportSummary
from picciuli.services import (
    AccountService,
    BudgetService,
    CategoryService,
    DebtService,
    GoalService,
    HistoryService,
    InvestmentService,
    PeriodService,
    ScheduleService,
    SecurityService,
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
    securities: SecurityService
    """Securities, prices and exchange rates."""
    investments: InvestmentService
    """Buying and selling shares, valuations and price refreshes."""
    schedules: ScheduleService
    """Recurring transactions."""
    debts: DebtService
    """Debt terms, payoff plans, loan payments and credit card predictions."""
    goals: GoalService
    """Savings goals, with dates, priorities and monthly amounts."""
    history: HistoryService
    """Cash flows and balances month by month or period by period."""

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
        self.securities = SecurityService(self._uow)
        self.investments = InvestmentService(self._uow, self.transactions)
        self.schedules = ScheduleService(self._uow)
        self.debts = DebtService(self._uow)
        self.goals = GoalService(self._uow)
        self.history = HistoryService(self._uow)

    @classmethod
    def open(cls, path: str | os.PathLike[str], *, create: bool = True) -> Book:
        """Open (and, if needed, create or upgrade) a database file.

        Older schema versions are upgraded in place, in a single transaction.
        First, a verified copy of the file is kept next to it as
        `<name>.schema-v<old version>.bak` (with `-2`, `-3`... if that name is
        taken): open it with the matching older release to get the data back
        as it was. Files already at the current version are not copied.

        Args:
            path: Path of the SQLite file.
            create: Whether to create the file if it does not exist.

        Returns:
            The opened book.

        Raises:
            FileNotFoundError: If the file does not exist and `create` is false.
            SchemaVersionError: If the file is not a Picciuli database, was
                written by a newer library version, or cannot be backed up
                before an upgrade.
        """
        if not create and not Path(path).exists():
            raise FileNotFoundError(f"database file not found: {os.fspath(path)}")
        engine = file_engine(path)
        try:
            prepare_schema(
                engine, backup=lambda version: backup_file(Path(path), version)
            )
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

    def import_from(self, source: Book, *, replace: bool = False) -> ImportSummary:
        """Copy every account, category, transaction, budget... of another book.

        The whole import runs in a single transaction: on error nothing changes.
        Every entity is created again through the services, so the source
        must respect the same rules as data entered by hand (balanced splits,
        non-negative holdings, valid settings, ...).

        When *merging* (the default), entities already present are reused
        instead of duplicated: accounts, categories and periods are matched by
        name (periods by first and last day), securities by ISIN or name,
        budgets, prices and exchange rates by category, security or currency
        and day, and transactions by content (day, description, notes and
        splits), so importing the same book twice adds nothing the second
        time. Existing entities and settings are never changed, and new
        transactions on accounts closed in this book are refused. A book
        without accounts, categories, transactions, securities or periods
        takes the settings of `source`.

        When *replacing*, everything stored in this book is deleted first and
        the settings of `source` are adopted.

        Args:
            source: Book to read; it is not modified.
            replace: Whether to erase this book before importing.

        Returns:
            How many entities were added.

        Raises:
            ConflictError: When merging books with a different currency or
                number of decimal digits (replace instead), or new
                transactions on an account closed in this book.
            ValidationError: If `source` is this book or its data breaks a
                domain rule.
        """
        if source is self:
            raise ValidationError("a book cannot be imported into itself")
        deadline = Deadline(None)
        with source._uow.session() as reading:
            raw = read_session(reading, deadline)
        return self._import(raw, replace=replace, deadline=deadline)

    def import_file(
        self,
        path: str | os.PathLike[str],
        *,
        replace: bool = False,
        timeout: float | None = 60.0,
    ) -> ImportSummary:
        """Import a database file that may come from an untrusted source.

        It works like [`import_from`][picciuli.Book.import_from], but the file
        is never opened as a `Book`: it is read once, read-only, and its
        schema must be exactly the one of the current
        [`SCHEMA_VERSION`][picciuli.Book.SCHEMA_VERSION], without views or
        triggers. Files with an older schema are refused: open them with
        `Book.open` (which upgrades them) and import them again.

        Args:
            path: Path of the SQLite file.
            replace: Whether to erase this book before importing.
            timeout: Time budget in seconds for the whole import, or `None`
                for no limit.

        Returns:
            How many entities were added.

        Raises:
            ValidationError: If the file is not a Picciuli database of the
                current schema version, its data breaks a domain rule, or the
                import takes longer than `timeout`.
            ConflictError: As for `import_from`.
        """
        deadline = Deadline(timeout)
        raw = read_file(path, deadline)
        return self._import(raw, replace=replace, deadline=deadline)

    def _import(
        self, raw: RawBook, *, replace: bool, deadline: Deadline
    ) -> ImportSummary:
        try:
            with self._uow.session() as writing:
                return import_book(
                    self, writing, raw, replace=replace, deadline=deadline
                )
        except PicciuliError:
            raise
        except Exception as exc:
            # Rows are validated one by one; anything unexpected is still a
            # problem of the imported data, never a reason to fail with a 500.
            raise ValidationError(
                f"the data cannot be imported ({type(exc).__name__})"
            ) from exc

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
