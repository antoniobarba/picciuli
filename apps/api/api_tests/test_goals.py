from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from api_tests.helpers import API, create_account

GOALS = f"{API}/goals"


def create_goal(api: TestClient, account_id: int, **extra: Any) -> dict[str, Any]:
    body = {"account_id": account_id, "name": "Holiday", "target_amount": 1200}
    response = api.post(GOALS, json={**body, **extra})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_create_update_and_delete(alice: TestClient) -> None:
    savings = create_account(alice, "Savings", "savings")
    goal = create_goal(alice, savings["id"], target_date="2026-01-31", priority="high")
    assert goal == {
        "id": goal["id"],
        "account_id": savings["id"],
        "name": "Holiday",
        "target_amount": 1200,
        "saved_amount": 0,
        "target_date": "2026-01-31",
        "priority": "high",
    }
    url = f"{GOALS}/{goal['id']}"
    updated = alice.patch(url, json={"saved_amount": 300, "target_date": None})
    assert (updated.json()["saved_amount"], updated.json()["target_date"]) == (
        300,
        None,
    )
    assert alice.patch(url, json={"name": None}).status_code == 422
    assert alice.get(url).json()["priority"] == "high"
    assert alice.get(GOALS, params={"account_id": savings["id"]}).json() == [
        updated.json()
    ]
    assert alice.delete(url).status_code == 204
    assert alice.get(url).status_code == 404


def test_report_plans_the_monthly_amount_and_warns(alice: TestClient) -> None:
    savings = create_account(alice, "Savings", "savings", opening_balance=500)
    create_goal(alice, savings["id"], target_amount=10001, target_date="2026-01-10")
    create_goal(alice, savings["id"], name="Car", target_amount=900, saved_amount=800)
    report = alice.get(f"{GOALS}/report", params={"today": "2025-11-30"}).json()
    assert report["today"] == "2025-11-30"
    (account,) = report["accounts"]
    assert account["account"]["name"] == "Savings"
    assert (account["balance"], account["assigned"]) == (500, 800)
    assert (account["unassigned"], account["shortfall"]) == (0, 300)
    trip, car = account["goals"]
    assert (trip["status"], trip["months_left"], trip["monthly_amount"]) == (
        "scheduled",
        3,
        3334,
    )
    assert (car["status"], car["remaining"], car["monthly_amount"]) == (
        "undated",
        100,
        None,
    )


def test_validation_and_rules(alice: TestClient) -> None:
    broker = create_account(alice, "Broker", "investment")
    savings = create_account(alice, "Savings", "savings")
    body = {"account_id": savings["id"], "name": "X", "target_amount": 1}
    assert alice.post(GOALS, json={**body, "target_amount": 0}).status_code == 422
    assert alice.post(GOALS, json={**body, "priority": "urgent"}).status_code == 422
    response = alice.post(GOALS, json={**body, "account_id": broker["id"]})
    assert response.status_code == 422
    assert "cannot hold savings goals" in response.text
    create_goal(alice, savings["id"])
    assert alice.post(GOALS, json={**body, "name": "holiday"}).status_code == 409
    response = alice.delete(f"{API}/accounts/{savings['id']}")
    assert response.status_code == 409


def test_goals_are_private(alice: TestClient, bob: TestClient) -> None:
    goal = create_goal(alice, create_account(alice, "Savings", "savings")["id"])
    assert bob.get(f"{GOALS}/{goal['id']}").status_code == 404
    assert bob.get(GOALS).json() == []
    assert bob.get(f"{GOALS}/report").json()["accounts"] == []
