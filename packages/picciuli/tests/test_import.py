from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest

from picciuli import (
    AccountSplit,
    AccountType,
    Book,
    ConflictError,
    ExternalSplit,
    ImportSummary,
    TradeKind,
    ValidationError,
)

from .conftest import d
from .schema_v1 import SCHEMA_V1


@pytest.fixture
def source() -> Iterator[Book]:
    with Book.in_memory() as book:
        book.settings.update(currency="€", currency_code="EUR", cost_method="fifo")
        checking = book.accounts.create("Checking", AccountType.CHECKING)
        broker = book.accounts.create("Broker", AccountType.INVESTMENT)
        food = book.categories.create("Food")
        groceries = book.categories.create("Groceries", parent_id=food.id)
        etf = book.securities.create(
            "All-World", currency="USD", kind="etf", isin="IE00BK5BQT80"
        )
        book.securities.set_price(etf.id, d(2), Decimal("10.5"))
        book.securities.set_exchange_rate("USD", d(2), Decimal("0.9"))
        period = book.periods.create(d(1), end=d(31), name="January")
        book.budgets.create(groceries.id, period.id, 30000)
        book.transactions.record_income(d(1), 500000, account_id=checking.id)
        book.transactions.record_expense(
            d(3), 4500, account_id=checking.id, category_id=groceries.id
        )
        book.transactions.record_expense(
            d(3), 4500, account_id=checking.id, category_id=groceries.id
        )
        book.investments.record_buy(
            d(2),
            account_id=broker.id,
            security_id=etf.id,
            quantity=Decimal(2),
            cost=2100,
        )
        yield book


def _snapshot(book: Book) -> dict[str, object]:
    return {
        "accounts": [(a.name, a.type, a.position) for a in book.accounts.list()],
        "categories": [(c.name, c.parent_id is None) for c in book.categories.list()],
        "transactions": len(book.transactions.list()),
        "balances": {b.account.name: b.balance for b in book.accounts.balances()},
        "periods": [(p.name, p.start, p.end) for p in book.periods.list()],
        "budgets": [b.amount for b in book.budgets.list()],
        "securities": [s.name for s in book.securities.list()],
    }


def test_into_empty_book_copies_everything(book: Book, source: Book) -> None:
    summary = book.import_from(source)
    assert summary == ImportSummary(
        replaced=False,
        accounts=2,
        categories=2,
        securities=1,
        prices=1,
        exchange_rates=1,
        periods=1,
        budgets=1,
        transactions=4,
        duplicates=0,
    )
    assert _snapshot(book) == _snapshot(source)
    assert book.settings.get() == source.settings.get()
    etf = book.securities.list()[0]
    assert [p.price for p in book.securities.prices(etf.id)] == [Decimal("10.5")]
    assert len(book.securities.exchange_rates("USD")) == 1


def test_merging_twice_adds_nothing(book: Book, source: Book) -> None:
    book.import_from(source)
    summary = book.import_from(source)
    assert summary.duplicates == 4
    assert (summary.accounts, summary.transactions, summary.prices) == (0, 0, 0)
    assert _snapshot(book) == _snapshot(source)


def test_merge_reuses_matching_entities(book: Book, source: Book) -> None:
    book.settings.update(currency="EUR", currency_code="EUR")
    book.accounts.create("Wallet", AccountType.CASH)
    mine = book.accounts.create("checking", AccountType.SAVINGS)
    living = book.categories.create("Living")
    book.categories.create("food", parent_id=living.id)
    book.transactions.record_expense(d(9), 100, account_id=mine.id)

    summary = book.import_from(source)

    assert (summary.accounts, summary.categories) == (1, 1)
    assert [(a.name, a.type, a.position) for a in book.accounts.list()] == [
        ("Wallet", AccountType.CASH, 1),
        ("checking", AccountType.SAVINGS, 2),
        ("Broker", AccountType.INVESTMENT, 3),
    ]
    # "Groceries" belonged to "Food", a subcategory here: it joins its parent.
    groceries = next(c for c in book.categories.list() if c.name == "Groceries")
    assert groceries.parent_id == living.id
    assert len(book.transactions.list(account_id=mine.id)) == 4
    assert book.settings.get().currency == "EUR"
    assert book.settings.get().cost_method == "average"


def test_merge_rejects_other_currencies(book: Book, source: Book) -> None:
    book.accounts.create("Wallet", AccountType.CASH)
    with pytest.raises(ConflictError, match="EUR into a book in USD"):
        book.import_from(source)
    book.settings.update(currency_code="EUR", minor_digits=3)
    with pytest.raises(ConflictError, match="decimal digits"):
        book.import_from(source)
    assert [a.name for a in book.accounts.list()] == ["Wallet"]


def test_replace_erases_the_book_first(book: Book, source: Book) -> None:
    wallet = book.accounts.create("Wallet", AccountType.CASH)
    food = book.categories.create("Food")
    book.categories.create("Snacks", parent_id=food.id)
    book.transactions.record_expense(d(9), 100, account_id=wallet.id)
    book.periods.create(d(1, 2))

    summary = book.import_from(source, replace=True)

    assert summary.replaced and summary.transactions == 4
    assert _snapshot(book) == _snapshot(source)
    assert book.settings.get() == source.settings.get()


def test_cannot_import_itself(book: Book) -> None:
    with pytest.raises(ValidationError):
        book.import_from(book)


def test_closed_accounts_stay_closed(book: Book, source: Book) -> None:
    old = source.accounts.create("Old", AccountType.CASH)
    source.transactions.record_income(d(1), 700, account_id=old.id)
    source.transactions.record_expense(d(2), 700, account_id=old.id)
    source.accounts.close(old.id, on=d(3))
    book.import_from(source)
    imported = next(a for a in book.accounts.list() if a.name == "Old")
    assert imported.closed_on == d(3)
    assert book.accounts.balance(imported.id) == 0


def test_merge_refuses_new_transactions_on_closed_accounts(
    book: Book, source: Book
) -> None:
    book.settings.update(currency="EUR", currency_code="EUR")
    mine = book.accounts.create("Checking", AccountType.CHECKING)
    book.accounts.close(mine.id, on=d(1, 12, 2024))
    with pytest.raises(ConflictError, match="closed"):
        book.import_from(source)
    assert [a.name for a in book.accounts.list()] == ["Checking"]


def _goal_values(book: Book) -> list[tuple[object, ...]]:
    names = {a.id: a.name for a in book.accounts.list()}
    return [
        (
            names[g.account_id],
            g.name,
            g.target_amount,
            g.saved_amount,
            g.target_date,
            g.priority,
        )
        for g in book.goals.list()
    ]


def test_goals_are_copied_merged_and_replaced(
    book: Book, source: Book, tmp_path: Path
) -> None:
    checking = source.accounts.list()[0]
    source.goals.create(checking.id, "Car", 900000, saved_amount=1000, priority="low")
    source.goals.create(checking.id, "Trip", 1500, target_date=d(31, 7))
    book.settings.update(currency="EUR", currency_code="EUR")
    wallet = book.accounts.create("Wallet", AccountType.CASH)
    mine = book.accounts.create("Checking", AccountType.CHECKING)
    book.goals.create(mine.id, "trip", 1500, target_date=d(31, 7))
    book.goals.create(wallet.id, "Mine", 10)

    # The account is matched by name and keeps its own id; an identical goal
    # (same name, case-insensitively) is not duplicated.
    assert book.import_from(source).goals == 1
    assert book.import_from(source).goals == 0
    assert [(g[0], g[1]) for g in _goal_values(book)] == [
        ("Wallet", "Mine"),
        ("Checking", "trip"),
        ("Checking", "Car"),
    ]

    path = _write(source, tmp_path / "goals.db")
    summary = book.import_file(path, replace=True)
    assert summary.goals == 2
    assert _goal_values(book) == _goal_values(source)


def test_merge_refuses_a_different_goal_with_the_same_name(
    book: Book, source: Book
) -> None:
    checking = source.accounts.list()[0]
    source.goals.create(checking.id, "Car", 900000, saved_amount=1000)
    book.settings.update(currency="EUR", currency_code="EUR")
    mine = book.accounts.create("Checking", AccountType.CHECKING)
    book.goals.create(mine.id, "car", 900000, saved_amount=2000)
    with pytest.raises(ConflictError, match="already has a different goal named 'car'"):
        book.import_from(source)
    assert len(book.transactions.list()) == 0
    assert book.goals.list()[0].saved_amount == 2000


# --- Untrusted files (SEC-01, SEC-04) ----------------------------------------


def _write(source: Book, path: Path) -> Path:
    with Book.open(path) as copy:
        copy.import_from(source)
    return path


def _tamper(path: Path, *statements: str) -> Path:
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA ignore_check_constraints=ON")
        for statement in statements:
            db.execute(statement)
        db.commit()
    return path


def test_file_round_trip(book: Book, source: Book, tmp_path: Path) -> None:
    path = _write(source, tmp_path / "export.db")
    content = path.read_bytes()
    summary = book.import_file(path)
    assert (summary.accounts, summary.transactions, summary.prices) == (2, 4, 1)
    assert _snapshot(book) == _snapshot(source)
    assert book.settings.get() == source.settings.get()
    (bought,) = [t for t in book.transactions.list() if t.trade is not None]
    assert bought.trade is not None
    assert (bought.trade.kind, bought.trade.quantity, bought.trade.amount) == (
        TradeKind.BUY,
        Decimal(2),
        2100,
    )
    assert book.import_file(path).duplicates == 4
    assert path.read_bytes() == content


_INFINITE = (
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) "
    "SELECT n AS id, 'x' AS name, '2025-01-01' AS start_date, NULL AS end_date "
    "FROM r"
)
_SPLITS_WITH = (
    "CREATE TABLE splits (id INTEGER NOT NULL, transaction_id INTEGER NOT NULL, "
    "position INTEGER NOT NULL, account_id INTEGER, category_id INTEGER, "
    "amount INTEGER NOT NULL, memo VARCHAR {}, security_id INTEGER, "
    "quantity INTEGER, PRIMARY KEY (id))"
)
_SPLIT_INDEXES = (
    "CREATE INDEX ix_splits_transaction_id ON splits (transaction_id)",
    "CREATE INDEX ix_splits_account ON splits (account_id)",
    "CREATE INDEX ix_splits_category ON splits (category_id)",
    "CREATE INDEX ix_splits_security ON splits (security_id)",
)


@pytest.mark.parametrize(
    ("statements", "message"),
    [
        pytest.param(
            (
                "DROP TABLE budgets",
                "DROP TABLE periods",
                f"CREATE VIEW periods AS {_INFINITE}",
            ),
            "view",
            id="infinite view",
        ),
        pytest.param(
            ("CREATE TRIGGER t AFTER UPDATE ON meta BEGIN SELECT 1; END",),
            "trigger",
            id="trigger",
        ),
        pytest.param(
            (
                "DROP TABLE splits",
                _SPLITS_WITH.format("AS (printf('%.*c', 999999999, 'x'))"),
                *_SPLIT_INDEXES,
            ),
            "structure",
            id="generated column",
        ),
        pytest.param(
            (
                "DROP TABLE splits",
                _SPLITS_WITH.format("DEFAULT (printf('%.*c', 999999999, 'x'))"),
                *_SPLIT_INDEXES,
            ),
            "structure",
            id="default expression",
        ),
        pytest.param(
            (
                "DROP INDEX ix_splits_account",
                "CREATE INDEX ix_splits_account ON splits (abs(account_id))",
            ),
            "structure",
            id="expression index",
        ),
        pytest.param(("CREATE TABLE evil (x)",), "unexpected", id="extra table"),
    ],
)
def test_file_with_a_malicious_schema_is_refused(
    book: Book,
    source: Book,
    tmp_path: Path,
    statements: tuple[str, ...],
    message: str,
) -> None:
    path = _tamper(_write(source, tmp_path / "evil.db"), *statements)
    start = time.perf_counter()
    with pytest.raises(ValidationError, match=message):
        book.import_file(path, replace=True)
    assert time.perf_counter() - start < 5
    assert book.accounts.list() == []


def test_old_schema_versions_are_refused_without_migrating_the_file(
    book: Book, tmp_path: Path
) -> None:
    path = tmp_path / "v1.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA_V1)
        db.execute("INSERT INTO meta VALUES ('schema_version', '1')")
        db.commit()
    content = path.read_bytes()
    with pytest.raises(ValidationError, match="old schema version 1"):
        book.import_file(path)
    assert path.read_bytes() == content


def test_file_that_is_not_a_book(book: Book, tmp_path: Path) -> None:
    path = tmp_path / "text.db"
    path.write_bytes(b"hello")
    with pytest.raises(ValidationError, match="not a Picciuli database"):
        book.import_file(path)


def test_import_has_a_time_budget(book: Book, source: Book, tmp_path: Path) -> None:
    path = _write(source, tmp_path / "export.db")
    with pytest.raises(ValidationError, match="in time"):
        book.import_file(path, timeout=0)
    assert book.accounts.list() == []


_FIRST_EXPENSES = (
    "transaction_id IN (SELECT id FROM transactions WHERE date = '2025-01-03')"
)


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (
            "UPDATE accounts SET opening_balance = 'abc'",
            "opening balance must be an integer",
        ),
        ("UPDATE accounts SET opening_balance = 1.5", "must be an integer"),
        ("UPDATE meta SET value = 'abc' WHERE key = 'minor_digits'", "minor digits"),
        ("UPDATE meta SET value = '9' WHERE key = 'minor_digits'", "minor digits"),
        ("UPDATE meta SET value = 'evil' WHERE key = 'cost_method'", "cost method"),
        (
            "UPDATE meta SET value = 'nope' WHERE key = 'price_provider'",
            "price provider",
        ),
        ("INSERT INTO meta VALUES ('evil', 'x')", "unknown setting"),
        (
            "UPDATE splits SET amount = 999999 WHERE id = (SELECT min(id) FROM splits)",
            "unbalanced",
        ),
        (
            "DELETE FROM trades; UPDATE splits SET quantity = -quantity",
            "cannot be negative",
        ),
        ("UPDATE trades SET amount = amount + 1", "trade does not match its splits"),
        ("UPDATE trades SET fee_category_id = 999", "fee category does not exist"),
        ("UPDATE trades SET kind = 'hold'", "kind must be"),
        (
            "UPDATE accounts SET type = 'checking' WHERE name = 'Broker'",
            "not an investment account",
        ),
        (
            "UPDATE accounts SET opening_date = '2030-01-01' WHERE name = 'Checking'",
            "opens on",
        ),
        (
            "UPDATE accounts SET closed_on = '2025-01-02' WHERE name = 'Checking'",
            "cannot be closed",
        ),
        ("UPDATE transactions SET date = '2025-13-45'", "not a valid date"),
        ("UPDATE transactions SET description = x'00ff'", "must be a string"),
        (
            "UPDATE splits SET category_id = 99 WHERE category_id IS NOT NULL",
            "does not exist",
        ),
        ("UPDATE securities SET isin = 'XX0000000000'", "invalid ISIN"),
        ("UPDATE prices SET price = -1", "greater than zero"),
        (
            "INSERT INTO savings_goals VALUES (1, 2, 'Bad', 100, 0, NULL, 'normal')",
            "savings goal 1 of the file: account 'Broker' cannot hold",
        ),
        (
            "INSERT INTO savings_goals VALUES (1, 1, 'Bad', 100, 0, NULL, 'urgent')",
            "invalid priority",
        ),
        (
            "INSERT INTO savings_goals VALUES (1, 9, 'Bad', 100, 0, NULL, 'normal')",
            "its account does not exist",
        ),
        (
            f"UPDATE splits SET amount = -4611686018427387904 WHERE {_FIRST_EXPENSES}",
            "amount cannot exceed",
        ),
    ],
)
def test_file_breaking_a_domain_rule_is_refused(
    book: Book, source: Book, tmp_path: Path, statement: str, message: str
) -> None:
    path = _tamper(_write(source, tmp_path / "bad.db"), *statement.split("; "))
    with pytest.raises(ValidationError, match=message):
        book.import_file(path, replace=True)
    assert book.accounts.list() == []
    assert book.transactions.list() == []
    assert book.settings.get().cost_method == "average"


@pytest.fixture
def scheduled(source: Book) -> Book:
    checking, _ = source.accounts.list()
    groceries = next(c for c in source.categories.list() if c.name == "Groceries")
    source.settings.update(period_start_day=27, period_weekend_shift=False)
    rent = source.schedules.create(
        d(5),
        [AccountSplit(checking.id, -1000), ExternalSplit(-1000, groceries.id)],
        description="Rent",
        mode="confirm",
    )
    source.schedules.post(rent.id)
    paused = source.schedules.create(
        d(20),
        [AccountSplit(checking.id, -50), ExternalSplit(-50)],
        frequency="weekly",
        every=2,
        occurrences=3,
    )
    source.schedules.update(paused.id, paused=True)
    return source


def test_schedules_are_copied_and_merged(
    book: Book, scheduled: Book, tmp_path: Path
) -> None:
    path = _write(scheduled, tmp_path / "export.db")
    summary = book.import_file(path)
    assert (summary.schedules, summary.transactions) == (2, 5)
    assert book.settings.get().period_start_day == 27
    assert book.settings.get().period_weekend_shift is False

    def shape(target: Book) -> list[tuple[object, ...]]:
        return [
            (
                *(s.description, s.frequency, s.every, s.next_date, s.remaining),
                *(s.mode, s.paused, len(s.splits), s.net_amount),
            )
            for s in target.schedules.list()
        ]

    assert shape(book) == shape(scheduled)
    rent = next(s for s in book.schedules.list() if s.description == "Rent")
    (linked,) = [t for t in book.transactions.list() if t.schedule_id is not None]
    assert (linked.schedule_id, linked.date) == (rent.id, d(5))

    again = book.import_file(path)
    assert (again.schedules, again.duplicates) == (0, 5)
    assert len(book.schedules.list()) == 2

    book.import_file(path, replace=True)
    assert shape(book) == shape(scheduled)


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE schedules SET frequency = 'hourly'", "invalid frequency"),
        ("UPDATE schedules SET mode = 'later'", "invalid mode"),
        ("UPDATE schedules SET paused = 2", "paused must be"),
        ("UPDATE schedules SET every = 0", "every must be"),
        ("UPDATE schedules SET next_date = 'soon'", "YYYY-MM-DD"),
        ("UPDATE schedules SET end_date = '2025-01-01'", "after the end day"),
        ("UPDATE schedules SET remaining = 0", "occurrences left"),
        (
            "UPDATE schedule_splits SET amount = amount * 2 WHERE position = 1",
            "unbalanced",
        ),
        (
            "UPDATE schedule_splits SET account_id = 99 WHERE position = 1",
            "account does not exist",
        ),
        ("UPDATE schedule_splits SET schedule_id = 99", "schedule does not exist"),
        ("UPDATE transactions SET schedule_id = 99", "schedule does not exist"),
        ("UPDATE meta SET value = 'x' WHERE key = 'period_start_day'", "start day"),
        ("UPDATE meta SET value = '40' WHERE key = 'period_start_day'", "start day"),
        ("UPDATE meta SET value = 'y' WHERE key = 'period_weekend_shift'", "weekend"),
    ],
)
def test_file_with_broken_schedules_is_refused(
    book: Book, scheduled: Book, tmp_path: Path, statement: str, message: str
) -> None:
    path = _tamper(_write(scheduled, tmp_path / "bad.db"), statement)
    with pytest.raises(ValidationError, match=message):
        book.import_file(path, replace=True)
    assert book.schedules.list() == []
