from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from api_tests.helpers import API, ISSUER, create_account
from picciuli import AccountType, Book
from picciuli_api import Settings
from picciuli_api.auth import User


class TestMe:
    def test_identity_and_book_creation(
        self, alice: TestClient, settings: Settings
    ) -> None:
        me = alice.get(f"{API}/me").json()
        assert me == {
            "id": User(ISSUER, "alice").id,
            "issuer": ISSUER,
            "subject": "alice",
        }
        assert (settings.users_dir / f"{me['id']}.db").is_file()

    def test_export(self, alice: TestClient, tmp_path: Path) -> None:
        create_account(alice, "Checking")
        response = alice.get(f"{API}/me/export")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/vnd.sqlite3"
        assert "picciuli.db" in response.headers["content-disposition"]
        target = tmp_path / "download.db"
        target.write_bytes(response.content)
        with Book.open(target, create=False) as book:
            assert [a.name for a in book.accounts.list()] == ["Checking"]

    def test_export_cleans_up_temporary_files(
        self, alice: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        exports = tmp_path / "exports"
        exports.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(exports))
        create_account(alice, "Checking")
        assert alice.get(f"{API}/me/export").status_code == 200
        assert list(exports.iterdir()) == []

    def test_export_without_data(self, alice: TestClient) -> None:
        response = alice.get(f"{API}/me/export")
        assert response.status_code == 404

    def test_delete(self, alice: TestClient, settings: Settings) -> None:
        create_account(alice, "Checking")
        assert alice.delete(f"{API}/me").status_code == 204
        assert not any(settings.users_dir.iterdir())
        assert alice.get(f"{API}/accounts").json() == []
        assert alice.delete(f"{API}/me").status_code == 204


def _database(path: Path, *names: str) -> bytes:
    with Book.open(path) as book:
        for name in names:
            account = book.accounts.create(name, AccountType.CHECKING)
            book.transactions.record_income(
                dt.date(2025, 1, 1), 1000, account_id=account.id
            )
    return path.read_bytes()


def _upload(client: TestClient, content: bytes, mode: str = "merge") -> Response:
    return client.post(
        f"{API}/me/import",
        params={"mode": mode},
        content=content,
        headers={"Content-Type": "application/vnd.sqlite3"},
    )


class TestImport:
    def test_merge_and_replace(self, alice: TestClient, tmp_path: Path) -> None:
        create_account(alice, "Wallet")
        content = _database(tmp_path / "local.db", "Checking", "Savings")
        merged = _upload(alice, content)
        assert merged.status_code == 200
        assert merged.json() == {
            "replaced": False,
            "accounts": 2,
            "categories": 0,
            "securities": 0,
            "prices": 0,
            "exchange_rates": 0,
            "periods": 0,
            "budgets": 0,
            "transactions": 2,
            "duplicates": 0,
            "schedules": 0,
            "goals": 0,
        }
        again = _upload(alice, content).json()
        assert (again["accounts"], again["duplicates"]) == (0, 2)
        names = [a["name"] for a in alice.get(f"{API}/accounts").json()]
        assert names == ["Wallet", "Checking", "Savings"]

        replaced = _upload(alice, content, "replace").json()
        assert replaced["replaced"] and replaced["accounts"] == 2
        names = [a["name"] for a in alice.get(f"{API}/accounts").json()]
        assert names == ["Checking", "Savings"]

    def test_merge_needs_the_same_currency(
        self, alice: TestClient, tmp_path: Path
    ) -> None:
        create_account(alice, "Wallet")
        path = tmp_path / "local.db"
        with Book.open(path) as book:
            book.settings.update(currency="€", currency_code="EUR")
        response = _upload(alice, path.read_bytes())
        assert response.status_code == 409
        assert _upload(alice, path.read_bytes(), "replace").status_code == 200
        assert alice.get(f"{API}/settings").json()["currency_code"] == "EUR"

    @pytest.mark.parametrize("kind", ["text", "empty sqlite", "damaged"])
    def test_rejects_other_files(
        self, alice: TestClient, tmp_path: Path, kind: str
    ) -> None:
        path = tmp_path / "other.db"
        if kind == "text":
            content = b"hello"
        elif kind == "empty sqlite":
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE things (id INTEGER)")
            content = path.read_bytes()
        else:
            content = _database(path, "Checking")[:2048]
        response = _upload(alice, content)
        assert response.status_code == 422
        assert alice.get(f"{API}/accounts").json() == []

    def test_size_limit(
        self, alice: TestClient, settings: Settings, tmp_path: Path
    ) -> None:
        settings.max_import_bytes = 100
        response = _upload(alice, _database(tmp_path / "local.db", "Checking"))
        assert response.status_code == 413
        assert response.json()["error"] == "too_large"

    def test_cleans_up_temporary_files(
        self, alice: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        content = _database(tmp_path / "local.db", "Checking")
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(uploads))
        assert _upload(alice, content).status_code == 200
        assert _upload(alice, b"junk").status_code == 422
        assert list(uploads.iterdir()) == []

    def test_needs_authentication(self, client: TestClient) -> None:
        assert _upload(client, b"").status_code == 401

    @pytest.mark.parametrize(
        "statement",
        [
            "CREATE VIEW evil AS WITH RECURSIVE r(n) AS "
            "(SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT n FROM r",
            "CREATE TRIGGER evil AFTER UPDATE ON meta BEGIN SELECT 1; END",
            "UPDATE accounts SET opening_balance = 'abc'",
            "UPDATE meta SET value = 'evil' WHERE key = 'cost_method'",
            "UPDATE splits SET amount = 999999 WHERE account_id IS NOT NULL",
            "UPDATE meta SET value = '1' WHERE key = 'schema_version'",
        ],
    )
    def test_rejects_unsafe_or_invalid_data(
        self, alice: TestClient, tmp_path: Path, statement: str
    ) -> None:
        create_account(alice, "Wallet")
        path = tmp_path / "local.db"
        _database(path, "Checking")
        with closing(sqlite3.connect(path)) as db:
            db.execute(statement)
            db.commit()
        for mode in ("merge", "replace"):
            response = _upload(alice, path.read_bytes(), mode)
            assert response.status_code == 422, response.json()
            assert response.json()["error"] == "validation_error"
        assert [a["name"] for a in alice.get(f"{API}/accounts").json()] == ["Wallet"]
        assert alice.get(f"{API}/settings").json()["cost_method"] == "average"

    def test_one_import_at_a_time(
        self, alice: TestClient, app: FastAPI, tmp_path: Path
    ) -> None:
        content = _database(tmp_path / "local.db", "Checking")
        imports = app.state.context.imports
        with imports.reserve(User(ISSUER, "alice").id):
            response = _upload(alice, content)
        assert response.status_code == 409
        imports.limit = 1
        with imports.reserve(User(ISSUER, "bob").id):
            response = _upload(alice, content)
        assert response.status_code == 503
        assert response.json()["error"] == "busy"
        assert response.headers["retry-after"] == "30"
        assert _upload(alice, content).status_code == 200


class TestSettings:
    def test_defaults_and_update(self, alice: TestClient) -> None:
        settings = alice.get(f"{API}/settings").json()
        assert settings["cost_method"] == "average"
        assert settings["price_provider"] == "yahoo"
        updated = alice.patch(
            f"{API}/settings",
            json={"currency": "€", "currency_code": "EUR", "cost_method": "fifo"},
        ).json()
        assert (updated["currency"], updated["currency_code"]) == ("€", "EUR")
        assert updated["cost_method"] == "fifo"
        assert updated["minor_digits"] == settings["minor_digits"]

    def test_unknown_provider(self, alice: TestClient) -> None:
        response = alice.patch(f"{API}/settings", json={"price_provider": "nope"})
        assert response.status_code == 422


class TestProviders:
    def test_lists(self, alice: TestClient) -> None:
        prices = alice.get(f"{API}/providers/prices").json()
        assert "yahoo" in [p["id"] for p in prices]
        rates = alice.get(f"{API}/providers/rates").json()
        assert "yahoo" in [p["id"] for p in rates]

    def test_search(self, alice: TestClient) -> None:
        found = alice.get(
            f"{API}/providers/prices/yahoo/search", params={"q": "vanguard"}
        ).json()
        assert found == [
            {
                "symbol": "VWCE.DE",
                "name": "Vanguard FTSE All-World",
                "exchange": "XETRA",
                "kind": "ETF",
                "currency": "EUR",
            }
        ]

    def test_search_failure_is_a_bad_gateway(self, alice: TestClient) -> None:
        response = alice.get(
            f"{API}/providers/prices/yahoo/search", params={"q": "fail"}
        )
        assert response.status_code == 502
        assert response.json()["error"] == "price_provider_error"

    def test_unknown_provider(self, alice: TestClient) -> None:
        response = alice.get(f"{API}/providers/prices/nope/search", params={"q": "x"})
        assert response.status_code == 502

    def test_empty_query(self, alice: TestClient) -> None:
        response = alice.get(f"{API}/providers/prices/yahoo/search", params={"q": ""})
        assert response.status_code == 422

    def test_providers_need_authentication(self, client: TestClient) -> None:
        assert client.get(f"{API}/providers/prices").status_code == 401
