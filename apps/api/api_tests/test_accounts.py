from __future__ import annotations

from fastapi.testclient import TestClient

from api_tests.helpers import API, create_account


def test_create_and_get(alice: TestClient) -> None:
    created = create_account(
        alice,
        "Mortgage",
        "mortgage",
        opening_balance=-15000000,
        opening_date="2025-01-01",
        notes="30 years",
    )
    assert created == {
        "id": created["id"],
        "name": "Mortgage",
        "type": "mortgage",
        "account_class": "liability",
        "opening_balance": -15000000,
        "opening_date": "2025-01-01",
        "goal": None,
        "notes": "30 years",
        "position": 1,
        "closed_on": None,
        "is_closed": False,
        "debt_terms": None,
    }
    assert alice.get(f"{API}/accounts/{created['id']}").json() == created


def test_list_and_move(alice: TestClient) -> None:
    first = create_account(alice, "First")
    create_account(alice, "Second", "savings")
    response = alice.post(f"{API}/accounts/{first['id']}/move", json={"position": 2})
    assert response.json()["position"] == 2
    names = [a["name"] for a in alice.get(f"{API}/accounts").json()]
    assert names == ["Second", "First"]


def test_partial_update(alice: TestClient) -> None:
    account = create_account(alice, "Savings", "savings", goal=100000, notes="rainy")
    url = f"{API}/accounts/{account['id']}"
    updated = alice.patch(url, json={"name": "Rainy day"}).json()
    assert (updated["name"], updated["goal"], updated["notes"]) == (
        "Rainy day",
        100000,
        "rainy",
    )
    cleared = alice.patch(url, json={"goal": None}).json()
    assert cleared["goal"] is None
    assert cleared["notes"] == "rainy"


def test_close_reopen_and_filter(alice: TestClient) -> None:
    account = create_account(alice, "Old")
    url = f"{API}/accounts/{account['id']}"
    closed = alice.post(f"{url}/close", json={"on": "2025-03-01"}).json()
    assert closed["closed_on"] == "2025-03-01"
    assert closed["is_closed"] is True
    assert alice.get(f"{API}/accounts", params={"include_closed": False}).json() == []
    assert alice.post(f"{url}/reopen").json()["is_closed"] is False
    assert alice.post(f"{url}/close").json()["is_closed"] is True


def test_close_with_balance_conflicts(alice: TestClient) -> None:
    account = create_account(alice, "Full", opening_balance=100)
    response = alice.post(f"{API}/accounts/{account['id']}/close")
    assert response.status_code == 409


def test_delete(alice: TestClient) -> None:
    account = create_account(alice)
    url = f"{API}/accounts/{account['id']}"
    response = alice.delete(url)
    assert response.status_code == 204
    assert response.content == b""
    assert alice.get(url).status_code == 404


def test_balances_and_net_worth(alice: TestClient) -> None:
    checking = create_account(alice, "Checking", opening_balance=50000)
    create_account(alice, "Card", "credit_card", opening_balance=-12000)
    alice.post(
        f"{API}/transactions/expense",
        json={"date": "2025-02-10", "amount": 2000, "account_id": checking["id"]},
    )
    balances = alice.get(f"{API}/accounts/balances").json()
    assert [(b["account"]["name"], b["balance"]) for b in balances] == [
        ("Checking", 48000),
        ("Card", -12000),
    ]
    before = alice.get(f"{API}/accounts/balances", params={"as_of": "2025-02-09"})
    assert before.json()[0]["balance"] == 50000
    assert alice.get(f"{API}/accounts/net-worth").json() == {
        "as_of": None,
        "assets": 48000,
        "liabilities": -12000,
        "net_worth": 36000,
    }
    balance = alice.get(
        f"{API}/accounts/{checking['id']}/balance", params={"as_of": "2025-02-10"}
    ).json()
    assert balance == {
        "account_id": checking["id"],
        "as_of": "2025-02-10",
        "balance": 48000,
    }


def test_trends(alice: TestClient) -> None:
    card = create_account(alice, "Card", "credit_card", opening_balance=-12000)
    for day in ("2025-01-10", "2025-02-10", "2025-03-01"):
        alice.post(
            f"{API}/transactions/income",
            json={"date": day, "amount": 3000, "account_id": card["id"]},
        )
    trends = alice.get(f"{API}/accounts/trends", params={"today": "2025-03-15"})
    assert trends.json() == [
        {
            "account": card,
            "balance": -3000,
            "months": 2,
            "average_flow": 3000,
            "low_point": -12000,
        }
    ]


def test_register(alice: TestClient) -> None:
    checking = create_account(alice, "Checking", opening_balance=1000)
    for day, amount in (("2025-01-05", 300), ("2025-01-20", 200)):
        alice.post(
            f"{API}/transactions/expense",
            json={"date": day, "amount": amount, "account_id": checking["id"]},
        )
    register = alice.get(
        f"{API}/accounts/{checking['id']}/register", params={"start": "2025-01-10"}
    ).json()
    assert register["starting_balance"] == 700
    assert [(e["amount"], e["balance"]) for e in register["entries"]] == [(-200, 500)]
    assert register["ending_balance"] == 500
    assert register["entries"][0]["transaction"]["kind"] == "expense"
