"""Every user only ever sees their own book."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api_tests.helpers import API, AUDIENCE, Tokens, create_account


def test_users_do_not_see_each_other(alice: TestClient, bob: TestClient) -> None:
    account = create_account(alice, "Alice's checking")
    assert bob.get(f"{API}/accounts").json() == []
    assert bob.get(f"{API}/accounts/{account['id']}").status_code == 404
    assert bob.get(f"{API}/transactions").json() == []


def test_same_ids_refer_to_different_data(alice: TestClient, bob: TestClient) -> None:
    alices = create_account(alice, "Alice's checking")
    bobs = create_account(bob, "Bob's checking")
    assert alices["id"] == bobs["id"]
    assert alice.get(f"{API}/accounts/{alices['id']}").json()["name"] == (
        "Alice's checking"
    )
    bob.patch(f"{API}/accounts/{bobs['id']}", json={"name": "Renamed by Bob"})
    bob.delete(f"{API}/accounts/{bobs['id']}")
    assert alice.get(f"{API}/accounts/{alices['id']}").json()["name"] == (
        "Alice's checking"
    )


def test_deleting_data_only_affects_oneself(alice: TestClient, bob: TestClient) -> None:
    create_account(alice, "Alice's")
    create_account(bob, "Bob's")
    assert bob.delete(f"{API}/me").status_code == 204
    assert [a["name"] for a in alice.get(f"{API}/accounts").json()] == ["Alice's"]
    assert bob.get(f"{API}/accounts").json() == []


def test_settings_are_per_user(alice: TestClient, bob: TestClient) -> None:
    alice.patch(f"{API}/settings", json={"currency_code": "CHF"})
    assert alice.get(f"{API}/settings").json()["currency_code"] == "CHF"
    assert bob.get(f"{API}/settings").json()["currency_code"] != "CHF"


def test_tokens_for_other_audiences_cannot_read_data(
    alice: TestClient, client: TestClient, tokens: Tokens
) -> None:
    create_account(alice, "Secret")
    token = tokens("alice", audience=f"not-{AUDIENCE}")
    response = client.get(
        f"{API}/accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
