from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from picciuli import Book, ConflictError, NotFoundError
from picciuli_api.auth import User
from picciuli_api.books import BookRegistry

ALICE = User("https://auth.test", "alice").id
BOB = User("https://auth.test", "bob").id
CAROL = User("https://auth.test", "carol").id


@pytest.fixture
def registry(tmp_path: Path) -> Iterator[BookRegistry]:
    registry = BookRegistry(tmp_path / "users", max_open=2)
    yield registry
    registry.close()


def lease_once(registry: BookRegistry, user_id: str) -> Book:
    with registry.lease(user_id) as book:
        return book


class TestLease:
    def test_creates_the_database_on_first_use(self, registry: BookRegistry) -> None:
        assert not registry.exists(ALICE)
        with registry.lease(ALICE) as book:
            book.accounts.create("Checking", "checking")
        assert registry.path_for(ALICE).is_file()
        assert registry.exists(ALICE)

    def test_reuses_the_open_book(self, registry: BookRegistry) -> None:
        assert lease_once(registry, ALICE) is lease_once(registry, ALICE)

    def test_data_persists_after_closing(self, registry: BookRegistry) -> None:
        with registry.lease(ALICE) as book:
            book.accounts.create("Checking", "checking")
        registry.close()
        with registry.lease(ALICE) as book:
            assert [a.name for a in book.accounts.list()] == ["Checking"]

    def test_rejects_ids_that_are_not_digests(self, registry: BookRegistry) -> None:
        for bad in ("../../etc/passwd", "ALICE", ALICE.upper(), ALICE + "0"):
            with pytest.raises(ValueError, match="invalid user id"):
                registry.path_for(bad)

    def test_rejects_empty_capacity(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="max_open"):
            BookRegistry(tmp_path, max_open=0)

    def test_concurrent_leases_share_one_book(self, registry: BookRegistry) -> None:
        books: list[Book] = []
        barrier = threading.Barrier(8)

        def work() -> None:
            barrier.wait()
            with registry.lease(ALICE) as book:
                book.accounts.list()
                books.append(book)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(books) == 8
        assert len({id(book) for book in books}) == 1


class TestEviction:
    def test_closes_the_least_recently_used(self, registry: BookRegistry) -> None:
        alice = lease_once(registry, ALICE)
        lease_once(registry, BOB)
        lease_once(registry, ALICE)
        lease_once(registry, CAROL)
        assert registry.open_count == 2
        assert lease_once(registry, ALICE) is alice
        assert registry.open_count == 2

    def test_never_closes_a_book_in_use(self, tmp_path: Path) -> None:
        registry = BookRegistry(tmp_path, max_open=1)
        with registry.lease(ALICE) as alice:
            lease_once(registry, BOB)
            lease_once(registry, CAROL)
            assert alice.accounts.list() == []
            assert lease_once(registry, ALICE) is alice
        assert registry.open_count == 1
        registry.close()
        assert registry.open_count == 0


class TestDelete:
    def test_deletes_the_file(self, registry: BookRegistry) -> None:
        lease_once(registry, ALICE)
        assert registry.delete(ALICE) is True
        assert not registry.exists(ALICE)
        assert registry.open_count == 0
        with registry.lease(ALICE) as book:
            assert book.accounts.list() == []

    def test_unknown_user(self, registry: BookRegistry) -> None:
        assert registry.delete(ALICE) is False

    def test_deletes_only_the_users_upgrade_backups(
        self, registry: BookRegistry
    ) -> None:
        lease_once(registry, ALICE)
        lease_once(registry, BOB)
        path = registry.path_for(ALICE)
        mine = [path.with_name(f"{path.name}.schema-v5{n}.bak") for n in ("", "-2")]
        other = registry.path_for(BOB).with_name(f"{BOB}.db.schema-v5.bak")
        for backup in [*mine, other]:
            backup.write_bytes(b"old")
        assert registry.delete(ALICE) is True
        assert not any(backup.exists() for backup in mine)
        assert other.exists()

    def test_refuses_while_in_use(self, registry: BookRegistry) -> None:
        with registry.lease(ALICE), pytest.raises(ConflictError):
            registry.delete(ALICE)
        assert registry.exists(ALICE)


class TestExport:
    def test_copies_the_database(self, registry: BookRegistry, tmp_path: Path) -> None:
        with registry.lease(ALICE) as book:
            book.accounts.create("Checking", "checking")
            target = tmp_path / "copy.db"
            registry.export(ALICE, target)
        with Book.open(target, create=False) as copy:
            assert [a.name for a in copy.accounts.list()] == ["Checking"]

    def test_copy_is_a_valid_sqlite_file(
        self, registry: BookRegistry, tmp_path: Path
    ) -> None:
        lease_once(registry, ALICE)
        target = tmp_path / "copy.db"
        registry.export(ALICE, target)
        connection = sqlite3.connect(target)
        try:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        finally:
            connection.close()

    def test_unknown_user(self, registry: BookRegistry, tmp_path: Path) -> None:
        with pytest.raises(NotFoundError):
            registry.export(ALICE, tmp_path / "copy.db")
