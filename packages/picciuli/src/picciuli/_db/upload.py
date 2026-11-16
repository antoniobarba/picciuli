"""Read the rows of a book from a trusted session or an untrusted file (private).

An uploaded file is attacker-controlled: its schema may hide views, triggers,
generated columns or default expressions that run SQL when read. It is
therefore opened read-only and immutable, with an untrusted schema and a time
budget, and its structure must match the current schema exactly before any
row is read. Rows are returned as plain tuples, never as ORM objects, and are
validated by the importer.
"""

from __future__ import annotations

import contextlib
import functools
import os
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Final

from sqlalchemy.orm import Session

from picciuli.errors import ValidationError

from .schema import SCHEMA_VERSION
from .tables import Base

COLUMNS: Final[Mapping[str, tuple[str, ...]]] = {
    "meta": ("key", "value"),
    "accounts": (
        "id",
        "name",
        "type",
        "opening_balance",
        "opening_date",
        "goal",
        "notes",
        "position",
        "closed_on",
    ),
    "categories": ("id", "name", "symbol", "parent_id", "position"),
    "securities": ("id", "name", "symbol", "isin", "currency", "kind", "notes"),
    "prices": ("id", "security_id", "date", "price", "source"),
    "exchange_rates": ("id", "currency", "date", "rate"),
    "periods": ("id", "name", "start_date", "end_date"),
    "budgets": ("id", "category_id", "period_id", "amount"),
    "transactions": ("id", "date", "description", "notes"),
    "splits": (
        "id",
        "transaction_id",
        "position",
        "account_id",
        "category_id",
        "amount",
        "memo",
        "security_id",
        "quantity",
    ),
    "trades": (
        "transaction_id",
        "kind",
        "account_id",
        "security_id",
        "quantity",
        "amount",
        "other_account_id",
        "fee",
        "fee_category_id",
        "tax",
        "tax_category_id",
        "gain_category_id",
    ),
}
"""Columns read from each table, in the order of the returned tuples."""

MAX_ROWS: Final = 1_000_000
"""Largest number of rows (all tables together) accepted in an imported book."""

RawBook = dict[str, list[tuple[object, ...]]]
"""Unvalidated rows of each table of `COLUMNS`."""

_SQLITE_MAGIC: Final = b"SQLite format 3\x00"
_PROGRESS_STEPS: Final = 10_000
_NOT_A_BOOK: Final = "the file is not a Picciuli database"

_Signature = tuple[object, ...]


class Deadline:
    """A time budget; `None` seconds means no limit."""

    def __init__(self, seconds: float | None) -> None:
        self._end = None if seconds is None else time.monotonic() + seconds

    @property
    def expired(self) -> bool:
        return self._end is not None and time.monotonic() > self._end

    def check(self) -> None:
        if self.expired:
            raise ValidationError(
                "the file is too large or too complex to import in time"
            )


def read_session(session: Session, deadline: Deadline) -> RawBook:
    """Read every row of a trusted book through its session."""
    connection = session.connection()

    def execute(sql: str) -> Iterable[tuple[object, ...]]:
        return (tuple(row) for row in connection.exec_driver_sql(sql))

    return _read_rows(execute, deadline)


def read_file(path: str | os.PathLike[str], deadline: Deadline) -> RawBook:
    """Read every row of an untrusted database file.

    Raises:
        ValidationError: If the file is not a Picciuli database of the current
            schema version, is damaged, or takes too long to read.
    """
    path = Path(path)
    try:
        with path.open("rb") as file:
            magic = file.read(len(_SQLITE_MAGIC))
    except OSError:
        raise ValidationError("the file cannot be read") from None
    if magic != _SQLITE_MAGIC:
        raise ValidationError(_NOT_A_BOOK)
    try:
        with _open_untrusted(path, deadline) as connection:
            _check_structure(connection)

            def execute(sql: str) -> Iterable[tuple[object, ...]]:
                return connection.execute(sql)

            return _read_rows(execute, deadline)
    except sqlite3.Error as exc:
        deadline.check()
        if "interrupt" in str(exc).lower():
            raise ValidationError("the file takes too long to read") from None
        raise ValidationError(f"{_NOT_A_BOOK} or it is damaged") from None


@contextlib.contextmanager
def _open_untrusted(path: Path, deadline: Deadline) -> Iterator[sqlite3.Connection]:
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        # Defense in depth where the Python/SQLite versions allow it (3.12+).
        if hasattr(connection, "setconfig"):
            for option, enabled in (
                ("SQLITE_DBCONFIG_DEFENSIVE", True),
                ("SQLITE_DBCONFIG_TRUSTED_SCHEMA", False),
                ("SQLITE_DBCONFIG_ENABLE_TRIGGER", False),
                ("SQLITE_DBCONFIG_ENABLE_VIEW", False),
            ):
                code = getattr(sqlite3, option, None)
                if code is not None:
                    with contextlib.suppress(sqlite3.Error):
                        connection.setconfig(code, enabled)
        for pragma in (
            "trusted_schema=OFF",
            "query_only=ON",
            "temp_store=MEMORY",
            "cache_size=-8192",
            "mmap_size=0",
            "cell_size_check=ON",
        ):
            connection.execute(f"PRAGMA {pragma}")
        connection.set_progress_handler(
            lambda: 1 if deadline.expired else 0, _PROGRESS_STEPS
        )
        yield connection
    finally:
        connection.close()


def _master(
    connection: sqlite3.Connection,
) -> dict[str, tuple[str, str, str | None]]:
    entries: dict[str, tuple[str, str, str | None]] = {}
    for kind, name, table, sql in connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master"
    ):
        entries[name] = (kind, table, sql)
    return entries


def _table_signature(connection: sqlite3.Connection, name: str) -> _Signature:
    return tuple(
        tuple(row)
        for row in connection.execute(
            'SELECT name, upper(type), "notnull", dflt_value, pk, hidden '
            "FROM pragma_table_xinfo(?) ORDER BY cid",
            (name,),
        )
    )


def _index_signature(
    connection: sqlite3.Connection, name: str, table: str
) -> _Signature:
    flags = tuple(
        tuple(row)
        for row in connection.execute(
            'SELECT "unique", origin, partial FROM pragma_index_list(?) WHERE name = ?',
            (table, name),
        )
    )
    columns = tuple(
        tuple(row)
        for row in connection.execute(
            'SELECT seqno, cid, name, "desc", coll, "key" '
            "FROM pragma_index_xinfo(?) ORDER BY seqno",
            (name,),
        )
    )
    return (table, flags, columns)


def _structure(
    connection: sqlite3.Connection,
    master: Mapping[str, tuple[str, str, str | None]],
) -> dict[str, _Signature]:
    result: dict[str, _Signature] = {}
    for name, (kind, table, _sql) in master.items():
        if kind == "table":
            result[name] = ("table", _table_signature(connection, name))
        else:
            result[name] = ("index", _index_signature(connection, name, table))
    return result


@functools.lru_cache(maxsize=1)
def _expected_structure() -> dict[str, _Signature]:
    from .schema import memory_engine

    engine = memory_engine()
    try:
        Base.metadata.create_all(engine)
        raw = engine.raw_connection()
        try:
            connection = raw.driver_connection
            assert isinstance(connection, sqlite3.Connection)
            return _structure(connection, _master(connection))
        finally:
            raw.close()
    finally:
        engine.dispose()


def _is_plain_table(sql: str | None) -> bool:
    words = (sql or "").split(None, 2)
    return [w.upper() for w in words[:2]] == ["CREATE", "TABLE"]


def _check_structure(connection: sqlite3.Connection) -> None:
    master = _master(connection)
    expected = _expected_structure()
    for name, (kind, _table, sql) in master.items():
        if kind not in {"table", "index"}:
            raise ValidationError(
                f"{_NOT_A_BOOK}: it contains the {kind} {name!r}, "
                "which is not part of the schema"
            )
        if kind == "table" and not _is_plain_table(sql):
            raise ValidationError(f"{_NOT_A_BOOK}: unexpected table {name!r}")
    if master.get("meta", ("",))[0] != "table" or not _is_plain_table(
        master["meta"][2]
    ):
        raise ValidationError(_NOT_A_BOOK)
    if _table_signature(connection, "meta") != expected["meta"][1]:
        raise ValidationError(_NOT_A_BOOK)
    _check_version(connection)
    unexpected = sorted(set(master) - set(expected))
    missing = sorted(set(expected) - set(master))
    if unexpected or missing:
        names = ", ".join(repr(n) for n in unexpected or missing)
        problem = "unexpected" if unexpected else "missing"
        raise ValidationError(f"{_NOT_A_BOOK}: {problem} schema entries {names}")
    found = _structure(connection, master)
    for name, signature in expected.items():
        if found[name] != signature:
            raise ValidationError(
                f"{_NOT_A_BOOK}: {name!r} does not have the expected structure"
            )


def _check_version(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchall()
    raw = rows[0][0] if len(rows) == 1 else None
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdigit():
        raise ValidationError(f"{_NOT_A_BOOK}: invalid schema version")
    version = int(raw)
    if version > SCHEMA_VERSION:
        raise ValidationError(
            f"the file uses schema version {version}, newer than the supported "
            f"version {SCHEMA_VERSION}"
        )
    if version < SCHEMA_VERSION:
        raise ValidationError(
            f"the file uses the old schema version {version}; open it once with "
            "an up-to-date Picciuli library (Book.open) to upgrade it, then "
            "import it again"
        )


def _read_rows(
    execute: Callable[[str], Iterable[tuple[object, ...]]], deadline: Deadline
) -> RawBook:
    total = 0
    for table in COLUMNS:
        for (count,) in execute(f'SELECT count(*) FROM "{table}"'):
            total += count if isinstance(count, int) else 0
    if total > MAX_ROWS:
        raise ValidationError(f"the file has more than {MAX_ROWS} rows")
    result: RawBook = {}
    for table, columns in COLUMNS.items():
        deadline.check()
        names = ", ".join(f'"{column}"' for column in columns)
        result[table] = [
            tuple(row) for row in execute(f'SELECT {names} FROM "{table}"')
        ]
    return result
