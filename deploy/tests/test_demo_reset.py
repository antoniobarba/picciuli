import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

import pytest
from deploy import reset_demo

from picciuli import AccountType, Book


def test_reset_replaces_data_seen_by_an_open_book(tmp_path: Path) -> None:
    path = tmp_path / "demo.db"
    today = dt.date(2026, 11, 15)
    with Book.open(path) as cached:
        cached.accounts.create("Visitor account", AccountType.CASH)
        cached.settings.update(currency="GBP")
        reset_demo.reset_book(path, today)
        assert len(cached.accounts.list()) == 6
        assert "Visitor account" not in {a.name for a in cached.accounts.list()}
        assert cached.settings.get().currency == "\u20ac"
        assert max(t.date for t in cached.transactions.list()) <= today
        cached.accounts.create("Another visitor account", AccountType.CASH)
        reset_demo.reset_book(path, today)
        assert len(cached.accounts.list()) == 6
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_seed_leaves_existing_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "demo.db"
    with Book.open(path) as book:
        book.accounts.create("Preserved", AccountType.CASH)

    def fail_seed(path: Path, today: dt.date) -> None:
        raise RuntimeError("seed failed")

    monkeypatch.setattr(reset_demo, "create_demo", fail_seed)
    with pytest.raises(RuntimeError, match="seed failed"):
        reset_demo.reset_book(path, dt.date(2026, 11, 15))
    with Book.open(path) as book:
        assert [a.name for a in book.accounts.list()] == ["Preserved"]


@pytest.mark.parametrize("username", ["demo", "another-user"])
def test_reset_is_pinned_and_does_not_require_a_password_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, username: str
) -> None:
    settings = reset_demo.Settings(
        oidc_issuer="https://issuer.example",
        oidc_audience="project",
        login_org_id="org",
        data_dir=tmp_path,
    )
    client = Mock()
    client.call.return_value = {
        "user": {
            "username": username,
            "details": {"resourceOwner": "org"},
            "state": "USER_STATE_ACTIVE",
            "human": {},
        }
    }
    reset = Mock()
    monkeypatch.setattr(
        Path, "read_text", lambda self: '{"user_id":"123","password":"test-only"}'
    )
    monkeypatch.setattr(reset_demo, "Settings", lambda: settings)
    monkeypatch.setattr(reset_demo, "Zitadel", lambda settings: client)
    monkeypatch.setattr(reset_demo, "reset_book", reset)
    if username != "demo":
        with pytest.raises(RuntimeError, match="unexpected demo identity"):
            reset_demo.main()
        assert client.call.call_count == 1
        reset.assert_not_called()
    else:
        reset_demo.main()
        client.call.assert_called_with(
            "POST",
            "/v2/users/123/password",
            {"newPassword": {"password": "test-only", "changeRequired": False}},
        )
        assert reset.call_args.args[0] == (
            tmp_path / "users" / f"{reset_demo.User(settings.oidc_issuer, '123').id}.db"
        )


def test_reset_unlocks_a_locked_out_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = reset_demo.Settings(
        oidc_issuer="https://issuer.example",
        oidc_audience="project",
        login_org_id="org",
        data_dir=tmp_path,
    )
    client = Mock()
    client.call.return_value = {
        "user": {
            "username": "demo",
            "details": {"resourceOwner": "org"},
            "state": "USER_STATE_LOCKED",
            "human": {},
        }
    }
    monkeypatch.setattr(
        Path, "read_text", lambda self: '{"user_id":"123","password":"test-only"}'
    )
    monkeypatch.setattr(reset_demo, "Settings", lambda: settings)
    monkeypatch.setattr(reset_demo, "Zitadel", lambda settings: client)
    monkeypatch.setattr(reset_demo, "reset_book", Mock())
    reset_demo.main()
    paths = [call.args[1] for call in client.call.call_args_list]
    assert paths == ["/v2/users/123", "/v2/users/123/unlock", "/v2/users/123/password"]
