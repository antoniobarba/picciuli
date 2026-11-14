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

SCHEMA_VERSION: Final = 1
"""Version of the schema created by this library release."""

MigrationStep = Callable[[Connection], None]

MIGRATIONS: Final[Mapping[int, MigrationStep]] = {}
"""Upgrade steps keyed by the version they upgrade *from* (step `n` -> `n + 1`).

When the schema changes, bump `SCHEMA_VERSION` and register the step here; all
steps run in a single transaction when an older database is opened.
"""

DEFAULT_SETTINGS: Final[Mapping[str, str]] = {"currency": "$", "minor_digits": "2"}


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
                "not a Picciuli database (legacy v1 files must be converted with "
                "tools/migrate_v1.py)"
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
