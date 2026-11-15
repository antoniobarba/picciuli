"""One private [`Book`][picciuli.Book] per user, kept open in a bounded cache."""

from __future__ import annotations

import contextlib
import re
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from picciuli import Book, ConflictError, NotFoundError

__all__ = ["BookRegistry", "ImportLimiter", "ImportsBusyError"]

_USER_ID = re.compile(r"[0-9a-f]{64}")
_SIDE_FILES = ("-journal", "-wal", "-shm")


@dataclass(slots=True)
class _Entry:
    book: Book
    leases: int = 0


class BookRegistry:
    """Open, cache and close the per-user databases.

    Each user owns the file `<directory>/<user id>.db`, created on first use.
    At most `max_open` books stay open; the least recently used ones that are
    not serving a request are closed when the limit is exceeded. Books in use
    are never closed, so the limit can be exceeded temporarily.

    The registry is thread-safe: requests run in a thread pool and every
    thread may lease books concurrently (a `Book` is itself thread-safe).

    Args:
        directory: Directory of the database files.
        max_open: Maximum number of idle books kept open.
    """

    def __init__(self, directory: Path, *, max_open: int = 64) -> None:
        if max_open < 1:
            raise ValueError("max_open must be at least 1")
        self.directory = directory
        self.max_open = max_open
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    @property
    def open_count(self) -> int:
        """Number of books currently open."""
        with self._lock:
            return len(self._entries)

    def path_for(self, user_id: str) -> Path:
        """Return the database file of a user.

        Raises:
            ValueError: If `user_id` is not a SHA-256 hex digest.
        """
        if not _USER_ID.fullmatch(user_id):
            raise ValueError("invalid user id")
        return self.directory / f"{user_id}.db"

    def exists(self, user_id: str) -> bool:
        """Return whether the user already has a database file."""
        return self.path_for(user_id).exists()

    @contextlib.contextmanager
    def lease(self, user_id: str) -> Iterator[Book]:
        """Borrow the user's book, opening (and creating) it if needed."""
        path = self.path_for(user_id)
        with self._lock:
            entry = self._entries.get(user_id)
            if entry is None:
                self.directory.mkdir(parents=True, exist_ok=True)
                entry = _Entry(Book.open(path))
                self._entries[user_id] = entry
            else:
                self._entries.move_to_end(user_id)
            entry.leases += 1
            self._evict_idle()
        try:
            yield entry.book
        finally:
            with self._lock:
                entry.leases -= 1
                self._evict_idle()

    def export(self, user_id: str, destination: Path) -> None:
        """Write a consistent copy of the user's database to `destination`.

        Raises:
            NotFoundError: If the user has no database yet.
        """
        path = self.path_for(user_id)
        if not path.exists():
            raise NotFoundError("no data stored for this user")
        source = sqlite3.connect(path)
        try:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()

    def delete(self, user_id: str) -> bool:
        """Close and delete the user's database.

        Returns:
            Whether a database file existed.

        Raises:
            ConflictError: If the book is serving other requests.
        """
        path = self.path_for(user_id)
        with self._lock:
            entry = self._entries.get(user_id)
            if entry is not None:
                if entry.leases:
                    raise ConflictError("the data is in use, try again later")
                del self._entries[user_id]
                entry.book.close()
            existed = path.exists()
            path.unlink(missing_ok=True)
            for suffix in _SIDE_FILES:
                path.with_name(path.name + suffix).unlink(missing_ok=True)
        return existed

    def close(self) -> None:
        """Close every open book."""
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            entry.book.close()

    def _evict_idle(self) -> None:
        excess = len(self._entries) - self.max_open
        if excess <= 0:
            return
        for user_id, entry in list(self._entries.items()):
            if excess <= 0:
                break
            if entry.leases == 0:
                del self._entries[user_id]
                entry.book.close()
                excess -= 1


class ImportLimiter:
    """Allow one import per user and at most `limit` imports at the same time.

    Imports are the most expensive requests (a file upload, then a long write
    transaction), so they are capped independently of the thread pool.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.limit = limit
        self._lock = threading.Lock()
        self._running: set[str] = set()

    @contextlib.contextmanager
    def reserve(self, user_id: str) -> Iterator[None]:
        """Hold an import slot for `user_id`.

        Raises:
            ConflictError: If the user already has an import running.
            ImportsBusyError: If `limit` imports are already running.
        """
        with self._lock:
            if user_id in self._running:
                raise ConflictError("an import of your data is already running")
            if len(self._running) >= self.limit:
                raise ImportsBusyError("too many imports are running, try again later")
            self._running.add(user_id)
        try:
            yield
        finally:
            with self._lock:
                self._running.discard(user_id)


class ImportsBusyError(Exception):
    """Every import slot of the server is taken."""
