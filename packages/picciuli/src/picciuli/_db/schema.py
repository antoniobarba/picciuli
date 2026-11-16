"""Engine creation and schema versioning (private)."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any, Final

from sqlalchemy import (
    URL,
    Connection,
    Engine,
    create_engine,
    event,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.pool import StaticPool

from picciuli.errors import SchemaVersionError

from .tables import Base, MetaRow

SCHEMA_VERSION: Final = 6
"""Version of the schema created by this library release."""

MigrationStep = Callable[[Connection], None]

# Schema version 2 adds securities, prices and exchange rates, and lets account
# splits move shares. The DDL is frozen here, independent from the ORM, so that
# this step keeps producing version 2 when later versions change the tables.
_V2_DDL: Final = (
    "ALTER TABLE splits RENAME TO splits_v1",
    "DROP INDEX ix_splits_transaction_id",
    "DROP INDEX ix_splits_account",
    "DROP INDEX ix_splits_category",
    """CREATE TABLE securities (
	id INTEGER NOT NULL,
	name VARCHAR COLLATE "NOCASE" NOT NULL,
	symbol VARCHAR,
	isin VARCHAR(12),
	currency VARCHAR(3) NOT NULL,
	kind VARCHAR NOT NULL,
	notes TEXT,
	PRIMARY KEY (id),
	CONSTRAINT ck_security_kind CHECK (kind IN ('stock', 'etf', 'fund', 'bond', """
    """'crypto', 'other')),
	CONSTRAINT ck_security_currency CHECK (length(currency) = 3),
	UNIQUE (name),
	UNIQUE (isin)
)""",
    """CREATE TABLE prices (
	id INTEGER NOT NULL,
	security_id INTEGER NOT NULL,
	date DATE NOT NULL,
	price INTEGER NOT NULL,
	source VARCHAR,
	PRIMARY KEY (id),
	CONSTRAINT ck_price_positive CHECK (price > 0),
	CONSTRAINT uq_price_security_date UNIQUE (security_id, date),
	FOREIGN KEY(security_id) REFERENCES securities (id) ON DELETE CASCADE
)""",
    """CREATE TABLE exchange_rates (
	id INTEGER NOT NULL,
	currency VARCHAR(3) NOT NULL,
	date DATE NOT NULL,
	rate INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_exchange_rate_positive CHECK (rate > 0),
	CONSTRAINT ck_exchange_rate_currency CHECK (length(currency) = 3),
	CONSTRAINT uq_exchange_rate_currency_date UNIQUE (currency, date)
)""",
    """CREATE TABLE splits (
	id INTEGER NOT NULL,
	transaction_id INTEGER NOT NULL,
	position INTEGER NOT NULL,
	account_id INTEGER,
	category_id INTEGER,
	amount INTEGER NOT NULL,
	memo VARCHAR,
	security_id INTEGER,
	quantity INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT ck_split_amount CHECK (amount != 0 OR security_id IS NOT NULL),
	CONSTRAINT ck_split_kind CHECK (account_id IS NULL OR category_id IS NULL),
	CONSTRAINT ck_split_security CHECK ((security_id IS NULL AND quantity IS NULL) """
    """OR (security_id IS NOT NULL AND quantity IS NOT NULL AND quantity != 0 """
    """AND account_id IS NOT NULL)),
	FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE,
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE RESTRICT,
	FOREIGN KEY(security_id) REFERENCES securities (id) ON DELETE RESTRICT
)""",
    "INSERT INTO splits (id, transaction_id, position, account_id, category_id, "
    "amount, memo) SELECT id, transaction_id, position, account_id, category_id, "
    "amount, memo FROM splits_v1",
    "DROP TABLE splits_v1",
    "CREATE INDEX ix_splits_transaction_id ON splits (transaction_id)",
    "CREATE INDEX ix_splits_account ON splits (account_id)",
    "CREATE INDEX ix_splits_category ON splits (category_id)",
    "CREATE INDEX ix_splits_security ON splits (security_id)",
)

_CURRENCY_CODES: Final[Mapping[str, str]] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₣": "CHF",
    "₹": "INR",
}


def guess_currency_code(currency: str) -> str | None:
    """ISO code matching a currency symbol or code, or `None` if unknown."""
    text = currency.strip()
    if len(text) == 3 and text.isascii() and text.isalpha():
        return text.upper()
    return _CURRENCY_CODES.get(text)


def _upgrade_1_to_2(connection: Connection) -> None:
    for statement in _V2_DDL:
        connection.exec_driver_sql(statement)
    currency = connection.scalar(select(MetaRow.value).where(MetaRow.key == "currency"))
    values = {"cost_method": "average", "price_provider": "yahoo"}
    code = guess_currency_code(currency or "")
    if code is not None:
        values["currency_code"] = code
    connection.execute(
        insert(MetaRow), [{"key": key, "value": value} for key, value in values.items()]
    )


# Schema version 3 stores the arguments of purchases and sales of shares in
# `trades`, so that they can be edited with the same form. Frozen like `_V2_DDL`.
_V3_DDL: Final = (
    """CREATE TABLE trades (
	transaction_id INTEGER NOT NULL,
	kind VARCHAR NOT NULL,
	account_id INTEGER NOT NULL,
	security_id INTEGER NOT NULL,
	quantity INTEGER NOT NULL,
	amount INTEGER NOT NULL,
	other_account_id INTEGER,
	fee INTEGER NOT NULL,
	fee_category_id INTEGER,
	tax INTEGER NOT NULL,
	tax_category_id INTEGER,
	gain_category_id INTEGER,
	PRIMARY KEY (transaction_id),
	CONSTRAINT ck_trade_kind CHECK (kind IN ('buy', 'sell')),
	CONSTRAINT ck_trade_quantity CHECK (quantity > 0),
	CONSTRAINT ck_trade_amount CHECK (amount > 0),
	CONSTRAINT ck_trade_fees CHECK (fee >= 0 AND tax >= 0),
	CONSTRAINT ck_trade_buy CHECK (kind = 'sell' OR (tax = 0 AND """
    """tax_category_id IS NULL AND gain_category_id IS NULL)),
	FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE,
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(security_id) REFERENCES securities (id) ON DELETE RESTRICT,
	FOREIGN KEY(other_account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(fee_category_id) REFERENCES categories (id) ON DELETE RESTRICT,
	FOREIGN KEY(tax_category_id) REFERENCES categories (id) ON DELETE RESTRICT,
	FOREIGN KEY(gain_category_id) REFERENCES categories (id) ON DELETE RESTRICT
)"""
)

# (account_id, category_id, amount, memo, security_id, quantity) of a split.
_V2Split = tuple[int | None, int | None, int, str | None, int | None, int | None]
# The same without the memo, which the comparison ignores.
_V2Key = tuple[int | None, int | None, int, int | None, int | None]


def _infer_trade(splits: list[_V2Split]) -> dict[str, Any] | None:
    """The trade a version 2 transaction was recorded from, if it is certain.

    Version 2 only stored the splits. A transaction becomes a trade when it
    has the shape that `record_buy` or `record_sell` produce, and only if
    rebuilding the splits from the inferred trade gives back exactly the
    stored accounts, categories, amounts and quantities; anything else stays
    an ordinary transaction. Sales may name their single unlabelled external
    split freely (for example imported "plusvalenza" lines): it is the gain.
    """
    shares = [s for s in splits if s[4] is not None]
    if len(shares) != 1:
        return None
    account, _, share_amount, _, security, quantity = shares[0]
    assert account is not None and quantity is not None
    cash = [s for s in splits if s[0] is not None and s[4] is None]
    external = [s for s in splits if s[0] is None]
    if len(cash) > 1:
        return None
    other = cash[0][0] if cash and cash[0][0] != account else None
    trade: dict[str, Any] = {
        "account_id": account,
        "security_id": security,
        "quantity": abs(quantity),
        "other_account_id": other,
        "fee": 0,
        "fee_category_id": None,
        "tax": 0,
        "tax_category_id": None,
        "gain_category_id": None,
    }
    if quantity > 0:
        if len(external) > 1 or not cash:
            return None
        trade.update(kind="buy", amount=share_amount)
        if external:
            trade.update(fee=-external[0][2], fee_category_id=external[0][1])
    else:
        labelled = {"Fee": "fee", "Tax": "tax", "Realized gain": "gain"}
        found: dict[str, _V2Split] = {}
        unlabelled = []
        for split in external:
            name = labelled.get((split[3] or "").strip())
            if name is None:
                unlabelled.append(split)
            elif name in found:
                return None
            else:
                found[name] = split
        if unlabelled:
            if len(unlabelled) > 1 or "gain" in found:
                return None
            found["gain"] = unlabelled[0]
        cost = -share_amount
        gain = found["gain"][2] if "gain" in found else 0
        trade.update(kind="sell", amount=cost + gain)
        if "gain" in found:
            trade["gain_category_id"] = found["gain"][1]
        if "fee" in found:
            trade.update(fee=-found["fee"][2], fee_category_id=found["fee"][1])
        if "tax" in found:
            trade.update(tax=-found["tax"][2], tax_category_id=found["tax"][1])
    if trade["amount"] <= 0 or trade["fee"] < 0 or trade["tax"] < 0:
        return None
    if Counter(_v2_trade_splits(trade, -share_amount)) != Counter(
        (s[0], s[1], s[2], s[4], s[5]) for s in splits
    ):
        return None
    return trade


def _v2_trade_splits(trade: dict[str, Any], cost: int) -> list[_V2Key]:
    """The splits `record_buy` or `record_sell` stored for `trade` (no memos)."""
    own, security = trade["account_id"], trade["security_id"]
    other = trade["other_account_id"] or own
    amount, fee, tax = trade["amount"], trade["fee"], trade["tax"]
    if trade["kind"] == "buy":
        result: list[_V2Key] = [
            (own, None, amount, security, trade["quantity"]),
            (other, None, -(amount + fee), None, None),
        ]
        if fee:
            result.append((None, trade["fee_category_id"], -fee, None, None))
        return result
    result = [(own, None, -cost, security, -trade["quantity"])]
    if amount - fee - tax:
        result.append((other, None, amount - fee - tax, None, None))
    if amount - cost:
        result.append((None, trade["gain_category_id"], amount - cost, None, None))
    if fee:
        result.append((None, trade["fee_category_id"], -fee, None, None))
    if tax:
        result.append((None, trade["tax_category_id"], -tax, None, None))
    return result


def _upgrade_2_to_3(connection: Connection) -> None:
    connection.exec_driver_sql(_V3_DDL)
    rows = connection.exec_driver_sql(
        "SELECT transaction_id, account_id, category_id, amount, memo, "
        "security_id, quantity FROM splits WHERE transaction_id IN "
        "(SELECT transaction_id FROM splits WHERE security_id IS NOT NULL) "
        "ORDER BY transaction_id, position, id"
    )
    grouped: dict[int, list[_V2Split]] = {}
    for transaction_id, *split in rows:
        grouped.setdefault(transaction_id, []).append(tuple(split))
    trades = []
    for transaction_id, splits in grouped.items():
        trade = _infer_trade(splits)
        if trade is not None:
            trades.append({"transaction_id": transaction_id, **trade})
    if trades:
        connection.execute(
            text(
                "INSERT INTO trades (transaction_id, kind, account_id, security_id, "
                "quantity, amount, other_account_id, fee, fee_category_id, tax, "
                "tax_category_id, gain_category_id) VALUES (:transaction_id, "
                ":kind, :account_id, :security_id, :quantity, :amount, "
                ":other_account_id, :fee, :fee_category_id, :tax, "
                ":tax_category_id, :gain_category_id)"
            ),
            trades,
        )


# Schema version 4 adds recurring transactions (`schedules` and their template
# splits) and links the transactions they record. Existing rows are never
# rewritten: `transactions` only gains a nullable last column, so that its
# layout matches a new database exactly. Frozen like `_V2_DDL`.
_V4_DDL: Final = (
    """CREATE TABLE schedules (
	id INTEGER NOT NULL,
	description VARCHAR,
	notes TEXT,
	frequency VARCHAR NOT NULL,
	every INTEGER NOT NULL,
	day_of_month INTEGER,
	next_date DATE,
	end_date DATE,
	remaining INTEGER,
	mode VARCHAR NOT NULL,
	paused BOOLEAN NOT NULL,
	last_error TEXT,
	PRIMARY KEY (id),
	CONSTRAINT ck_schedule_frequency CHECK (frequency IN ('daily', 'weekly', """
    """'monthly', 'yearly')),
	CONSTRAINT ck_schedule_every CHECK (every >= 1),
	CONSTRAINT ck_schedule_day_of_month CHECK ((frequency IN ('monthly', """
    """'yearly') AND day_of_month BETWEEN 1 AND 31) OR (frequency IN ('daily', """
    """'weekly') AND day_of_month IS NULL)),
	CONSTRAINT ck_schedule_remaining CHECK (remaining IS NULL OR remaining >= 0),
	CONSTRAINT ck_schedule_mode CHECK (mode IN ('auto', 'confirm')),
	CONSTRAINT ck_schedule_paused CHECK (paused IN (0, 1))
)""",
    "CREATE INDEX ix_schedules_next_date ON schedules (next_date)",
    """CREATE TABLE schedule_splits (
	id INTEGER NOT NULL,
	schedule_id INTEGER NOT NULL,
	position INTEGER NOT NULL,
	account_id INTEGER,
	category_id INTEGER,
	amount INTEGER NOT NULL,
	memo VARCHAR,
	PRIMARY KEY (id),
	CONSTRAINT ck_schedule_split_amount CHECK (amount != 0),
	CONSTRAINT ck_schedule_split_kind CHECK (account_id IS NULL OR """
    """category_id IS NULL),
	FOREIGN KEY(schedule_id) REFERENCES schedules (id) ON DELETE CASCADE,
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_schedule_splits_schedule_id ON schedule_splits (schedule_id)",
    "CREATE INDEX ix_schedule_splits_category ON schedule_splits (category_id)",
    "CREATE INDEX ix_schedule_splits_account ON schedule_splits (account_id)",
    "ALTER TABLE transactions ADD COLUMN schedule_id INTEGER",
    "CREATE INDEX ix_transactions_schedule_id ON transactions (schedule_id)",
)


def _upgrade_3_to_4(connection: Connection) -> None:
    for statement in _V4_DDL:
        connection.exec_driver_sql(statement)
    # Existing books keep creating their periods by hand until asked otherwise.
    connection.execute(
        insert(MetaRow),
        [
            {"key": "period_start_day", "value": ""},
            {"key": "period_weekend_shift", "value": "1"},
        ],
    )


# Schema version 5 adds the interest and payment terms of liabilities
# (`debt_terms`) and ties schedules to loans and credit cards
# (`schedule_debts`). It only creates new, empty tables: no existing row is
# touched, and liabilities simply have no terms yet. Frozen like `_V2_DDL`.
_V5_DDL: Final = (
    """CREATE TABLE debt_terms (
	account_id INTEGER NOT NULL,
	annual_rate INTEGER NOT NULL,
	payment INTEGER,
	payment_percent INTEGER,
	due_day INTEGER,
	statement_day INTEGER,
	credit_limit INTEGER,
	payment_account_id INTEGER,
	interest_category_id INTEGER,
	PRIMARY KEY (account_id),
	CONSTRAINT ck_debt_terms_rate CHECK (annual_rate >= 0),
	CONSTRAINT ck_debt_terms_payment CHECK (payment IS NULL OR payment > 0),
	CONSTRAINT ck_debt_terms_percent CHECK (payment_percent IS NULL OR """
    """payment_percent > 0),
	CONSTRAINT ck_debt_terms_due_day CHECK (due_day IS NULL OR due_day """
    """BETWEEN 1 AND 31),
	CONSTRAINT ck_debt_terms_statement_day CHECK (statement_day IS NULL OR """
    """statement_day BETWEEN 1 AND 31),
	CONSTRAINT ck_debt_terms_limit CHECK (credit_limit IS NULL OR """
    """credit_limit > 0),
	CONSTRAINT ck_debt_terms_payment_account CHECK (payment_account_id IS NULL """
    """OR payment_account_id != account_id),
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE,
	FOREIGN KEY(payment_account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(interest_category_id) REFERENCES categories (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE schedule_debts (
	schedule_id INTEGER NOT NULL,
	account_id INTEGER NOT NULL,
	kind VARCHAR NOT NULL,
	interest_category_id INTEGER,
	PRIMARY KEY (schedule_id),
	CONSTRAINT ck_schedule_debt_kind CHECK (kind IN ('loan_payment', """
    """'card_interest', 'card_min_payment')),
	CONSTRAINT ck_schedule_debt_category CHECK (kind = 'loan_payment' OR """
    """interest_category_id IS NULL),
	FOREIGN KEY(schedule_id) REFERENCES schedules (id) ON DELETE CASCADE,
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(interest_category_id) REFERENCES categories (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_schedule_debts_account_id ON schedule_debts (account_id)",
)


def _upgrade_4_to_5(connection: Connection) -> None:
    for statement in _V5_DDL:
        connection.exec_driver_sql(statement)


# Schema version 6 adds the fixed charges included in every payment of a loan
# (`debt_charges`). It only creates a new, empty table. Frozen like `_V2_DDL`.
_V6_DDL: Final = (
    """CREATE TABLE debt_charges (
	id INTEGER NOT NULL,
	account_id INTEGER NOT NULL,
	position INTEGER NOT NULL,
	amount INTEGER NOT NULL,
	category_id INTEGER,
	label VARCHAR,
	PRIMARY KEY (id),
	CONSTRAINT ck_debt_charge_amount CHECK (amount > 0),
	CONSTRAINT ck_debt_charge_position CHECK (position >= 1),
	FOREIGN KEY(account_id) REFERENCES debt_terms (account_id) ON DELETE CASCADE,
	FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_debt_charges_account_id ON debt_charges (account_id)",
    "CREATE INDEX ix_debt_charges_category_id ON debt_charges (category_id)",
)


def _upgrade_5_to_6(connection: Connection) -> None:
    for statement in _V6_DDL:
        connection.exec_driver_sql(statement)


MIGRATIONS: Final[Mapping[int, MigrationStep]] = {
    1: _upgrade_1_to_2,
    2: _upgrade_2_to_3,
    3: _upgrade_3_to_4,
    4: _upgrade_4_to_5,
    5: _upgrade_5_to_6,
}
"""Upgrade steps keyed by the version they upgrade *from* (step `n` -> `n + 1`).

When the schema changes, bump `SCHEMA_VERSION` and register the step here; all
steps run in a single transaction when an older database is opened.
"""

DEFAULT_SETTINGS: Final[Mapping[str, str]] = {
    "currency": "$",
    "minor_digits": "2",
    "currency_code": "USD",
    "cost_method": "average",
    "price_provider": "yahoo",
    "rate_provider": "yahoo",
    "period_start_day": "1",
    "period_weekend_shift": "1",
}


def _install_hooks(engine: Engine) -> None:
    # Let SQLAlchemy, not the sqlite3 driver, control transactions so that DDL and
    # migrations are transactional too (recipe from the SQLAlchemy SQLite docs).
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def file_engine(path: str | os.PathLike[str]) -> Engine:
    engine = create_engine(URL.create("sqlite+pysqlite", database=os.fspath(path)))
    _install_hooks(engine)
    return engine


def memory_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    _install_hooks(engine)
    return engine


def prepare_schema(
    engine: Engine,
    *,
    target_version: int = SCHEMA_VERSION,
    migrations: Mapping[int, MigrationStep] = MIGRATIONS,
) -> None:
    """Create a new schema, upgrade an older one or reject an unusable file."""
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if not tables:
            Base.metadata.create_all(connection)
            values = {"schema_version": str(target_version), **DEFAULT_SETTINGS}
            connection.execute(
                insert(MetaRow),
                [{"key": key, "value": value} for key, value in values.items()],
            )
            return
        if "meta" not in tables:
            raise SchemaVersionError(
                "not a Picciuli database (legacy v1 files are not supported)"
            )
        raw = connection.scalar(
            select(MetaRow.value).where(MetaRow.key == "schema_version")
        )
        try:
            version = int(raw) if raw is not None else None
        except ValueError:
            version = None
        if version is None or version < 1:
            raise SchemaVersionError(f"invalid schema version: {raw!r}")
        if version > target_version:
            raise SchemaVersionError(
                f"database schema version {version} is newer than the supported "
                f"version {target_version}; upgrade the library"
            )
        if version == target_version:
            return
        for current in range(version, target_version):
            step = migrations.get(current)
            if step is None:
                raise SchemaVersionError(
                    f"no migration from schema version {current} to {current + 1}"
                )
            step(connection)
        connection.execute(
            update(MetaRow)
            .where(MetaRow.key == "schema_version")
            .values(value=str(target_version))
        )
