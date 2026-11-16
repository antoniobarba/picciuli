from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from api_tests.helpers import API, create_account, create_category

CARD_TERMS: dict[str, Any] = {
    "annual_rate": "19.9",
    "payment": 2500,
    "payment_percent": "3",
    "due_day": 15,
    "statement_day": 1,
    "credit_limit": 300000,
}


def _transfer(from_id: int, to_id: int, amount: int) -> list[dict[str, Any]]:
    return [
        {"type": "account", "account_id": from_id, "amount": -amount},
        {"type": "account", "account_id": to_id, "amount": amount},
    ]


def test_card_terms_and_proposed_minimum_payments(alice: TestClient) -> None:
    checking = create_account(alice, "Checking")
    savings = create_account(alice, "Savings", "savings")
    card = create_account(
        alice,
        "Visa",
        "credit_card",
        opening_balance=-100000,
        debt_terms={
            **CARD_TERMS,
            "payment_account_id": checking["id"],
            "new_interest_category": "Visa interest",
            "propose_interest": True,
            "propose_minimum": True,
        },
    )
    (category,) = alice.get(f"{API}/categories").json()
    assert category["name"] == "Visa interest"
    assert card["debt_terms"] == {
        **CARD_TERMS,
        "payment_account_id": checking["id"],
        "interest_category_id": category["id"],
        "propose_interest": True,
        "propose_minimum": True,
        "charges": [],
    }
    schedules = alice.get(f"{API}/schedules").json()
    kinds = {s["debt"]["kind"]: s for s in schedules}
    assert set(kinds) == {"card_interest", "card_min_payment"}
    minimum = kinds["card_min_payment"]
    assert (minimum["mode"], minimum["splits"], minimum["day_of_month"]) == (
        "confirm",
        [],
        15,
    )
    response = alice.patch(
        f"{API}/schedules/{minimum['id']}", json={"description": "Mine"}
    )
    assert response.status_code == 409

    day = minimum["next_date"]
    (occurrence,) = alice.get(
        f"{API}/schedules/occurrences", params={"start": day, "end": day}
    ).json()
    assert occurrence["amount"] == 3000
    assert [s["account_id"] for s in occurrence["splits"]] == [
        checking["id"],
        card["id"],
    ]
    response = alice.post(
        f"{API}/schedules/{minimum['id']}/post",
        json={"from_account_id": savings["id"], "amount": 5000},
    )
    assert response.status_code == 201, response.text
    assert [(s["account_id"], s["amount"]) for s in response.json()["splits"]] == [
        (savings["id"], -5000),
        (card["id"], 5000),
    ]

    removed = alice.patch(f"{API}/accounts/{card['id']}", json={"debt_terms": None})
    assert removed.json()["debt_terms"] is None
    assert alice.get(f"{API}/schedules").json() == []


def test_terms_are_validated(alice: TestClient) -> None:
    checking = create_account(alice, "Checking")
    response = alice.patch(
        f"{API}/accounts/{checking['id']}", json={"debt_terms": {"annual_rate": 5}}
    )
    assert response.status_code == 422
    assert "not a liability" in response.json()["detail"]
    response = alice.post(
        f"{API}/accounts",
        json={
            "name": "Loan",
            "type": "loan",
            "debt_terms": {"annual_rate": "5", "statement_day": 3},
        },
    )
    assert response.status_code == 422
    assert "only credit cards" in response.json()["detail"]
    # The account created before the terms were refused is rolled back.
    assert [a["name"] for a in alice.get(f"{API}/accounts").json()] == ["Checking"]
    response = alice.post(
        f"{API}/accounts",
        json={
            "name": "Loan",
            "type": "loan",
            "debt_terms": {
                "annual_rate": "5",
                "interest_category_id": 1,
                "new_interest_category": "Interest",
            },
        },
    )
    assert response.status_code == 422


def test_loan_payments_and_plans(alice: TestClient) -> None:
    checking = create_account(alice, "Checking")
    interest = create_category(alice, "Interest")
    mortgage = create_account(
        alice,
        "Mortgage",
        "mortgage",
        opening_balance=-15000000,
        debt_terms={
            "annual_rate": "3",
            "payment": 80000,
            "due_day": 5,
            "interest_category_id": interest["id"],
        },
    )
    create_account(
        alice,
        "Card",
        "credit_card",
        opening_balance=-200000,
        debt_terms={"annual_rate": "24", "payment": 5000},
    )
    url = f"{API}/debts/{mortgage['id']}"
    split = alice.get(
        f"{url}/payment-split", params={"date": "2025-01-05", "amount": 80000}
    ).json()
    assert (split["interest"], split["principal"]) == (37500, 42500)
    response = alice.post(
        f"{url}/payments",
        json={"date": "2025-01-05", "amount": 80000, "from_account_id": checking["id"]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["splits"][-1] == {
        "type": "external",
        "amount": -37500,
        "category_id": interest["id"],
        "memo": "Interest",
    }

    debts = alice.get(f"{API}/debts", params={"today": "2025-01-31"}).json()
    assert [(d["account"]["name"], d["owed"]) for d in debts] == [
        ("Mortgage", 15000000 - 42500),
        ("Card", 200000),
    ]
    assert debts[0]["payoff"] is not None

    plans = alice.post(
        f"{API}/debts/plan",
        json={
            "extra": 10000,
            "lump_sums": [{"date": "2025-06-01", "amount": 50000}],
            "today": "2025-01-31",
        },
    ).json()
    assert plans["avalanche"]["debts"][0]["account_id"] != mortgage["id"]
    assert plans["snowball"]["strategy"] == "snowball"
    assert plans["avalanche"]["months"][0]["month"] == "2025-02-01"

    schedule = alice.post(
        f"{API}/schedules",
        json={
            "start": "2025-02-05",
            "splits": _transfer(checking["id"], mortgage["id"], 80000),
            "debt": {"account_id": mortgage["id"]},
        },
    )
    assert schedule.status_code == 201, schedule.text
    assert schedule.json()["debt"] == {
        "kind": "loan_payment",
        "account_id": mortgage["id"],
        "interest_category_id": None,
    }
    (occurrence,) = alice.get(
        f"{API}/schedules/occurrences",
        params={"start": "2025-02-01", "end": "2025-02-28"},
    ).json()
    assert occurrence["amount"] == 80000
    assert occurrence["splits"][-1]["amount"] == -37394


def test_loan_payments_include_fixed_charges(alice: TestClient) -> None:
    checking = create_account(alice, "Checking")
    insurance = create_category(alice, "Insurance")
    charge = {"amount": 709, "category_id": insurance["id"], "label": "Insurance"}
    loan = create_account(
        alice,
        "Loan",
        "loan",
        opening_balance=-952000,
        debt_terms={
            "annual_rate": "8.99",
            "payment": 13371,
            "new_interest_category": "Loan interest",
            "charges": [charge],
        },
    )
    assert loan["debt_terms"]["charges"] == [charge]
    url = f"{API}/debts/{loan['id']}"
    split = alice.get(
        f"{url}/payment-split", params={"date": "2026-11-16", "amount": 13371}
    ).json()
    assert (split["interest"], split["charges"], split["principal"]) == (
        7132,
        [charge],
        5530,
    )
    response = alice.post(
        f"{url}/payments",
        json={"date": "2026-11-16", "amount": 13371, "from_account_id": checking["id"]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["splits"][-1] == {
        "type": "external",
        "amount": -709,
        "category_id": insurance["id"],
        "memo": "Insurance",
    }
    (debt,) = alice.get(f"{API}/debts", params={"today": "2026-11-16"}).json()
    assert debt["charges_to_payoff"] > 0
    plan = alice.post(f"{API}/debts/plan", json={"today": "2026-11-16"}).json()
    assert plan["avalanche"]["total_charges"] == debt["charges_to_payoff"]

    response = alice.patch(
        f"{API}/accounts/{loan['id']}",
        json={
            "debt_terms": {
                "annual_rate": "8.99",
                "payment": 700,
                "charges": [charge],
            }
        },
    )
    assert response.status_code == 422
    assert "less than the payment" in response.json()["detail"]
