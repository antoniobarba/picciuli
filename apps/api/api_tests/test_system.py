from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_tests.helpers import API, ISSUER, create_account
from picciuli import Book
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
