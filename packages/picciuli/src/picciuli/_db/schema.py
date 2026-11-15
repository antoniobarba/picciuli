"""Engine creation and schema versioning (private)."""

from __future__ import annotations

import os
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
    update,
)
from sqlalchemy.pool import StaticPool

from picciuli.errors import SchemaVersionError

from .tables import Base, MetaRow

SCHEMA_VERSION: Final = 2
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


MIGRATIONS: Final[Mapping[int, MigrationStep]] = {1: _upgrade_1_to_2}
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
