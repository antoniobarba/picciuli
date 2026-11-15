from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_tests.helpers import API, create_account, create_category


@pytest.fixture
def tree(alice: TestClient) -> dict[str, dict[str, Any]]:
    food = create_category(alice, "Food", symbol="FOOD")
    groceries = create_category(alice, "Groceries", parent_id=food["id"])
    home = create_category(alice, "Home")
    return {"food": food, "groceries": groceries, "home": home}


def test_create_and_list(alice: TestClient, tree: dict[str, dict[str, Any]]) -> None:
    assert tree["groceries"]["parent_id"] == tree["food"]["id"]
    assert tree["food"]["symbol"] == "FOOD"
    names = [c["name"] for c in alice.get(f"{API}/categories").json()]
    assert names == ["Food", "Groceries", "Home"]
    top = alice.get(f"{API}/categories", params={"top_level": True}).json()
    assert [c["name"] for c in top] == ["Food", "Home"]


def test_get_and_children(alice: TestClient, tree: dict[str, dict[str, Any]]) -> None:
    food_id = tree["food"]["id"]
    assert alice.get(f"{API}/categories/{food_id}").json() == tree["food"]
    children = alice.get(f"{API}/categories/{food_id}/children").json()
    assert children == [tree["groceries"]]
    assert alice.get(f"{API}/categories/999/children").status_code == 404


def test_update_and_reparent(
    alice: TestClient, tree: dict[str, dict[str, Any]]
) -> None:
    url = f"{API}/categories/{tree['groceries']['id']}"
    renamed = alice.patch(url, json={"name": "Supermarket"}).json()
    assert renamed["name"] == "Supermarket"
    assert renamed["parent_id"] == tree["food"]["id"]
    top = alice.patch(url, json={"parent_id": None}).json()
    assert top["parent_id"] is None


def test_child_of_a_child_is_refused(
    alice: TestClient, tree: dict[str, dict[str, Any]]
) -> None:
    response = alice.post(
        f"{API}/categories",
        json={"name": "Too deep", "parent_id": tree["groceries"]["id"]},
    )
    assert response.status_code in (409, 422)


@pytest.fixture
def used_food(alice: TestClient, tree: dict[str, dict[str, Any]]) -> int:
    account = create_account(alice)
    response = alice.post(
        f"{API}/transactions/expense",
        json={
            "date": "2025-01-02",
            "amount": 500,
            "account_id": account["id"],
            "category_id": tree["home"]["id"],
        },
    )
    assert response.status_code == 201
    transaction_id: int = response.json()["id"]
    return transaction_id


def test_delete_in_use_needs_a_decision(
    alice: TestClient, tree: dict[str, dict[str, Any]], used_food: int
) -> None:
    response = alice.delete(f"{API}/categories/{tree['home']['id']}")
    assert response.status_code == 409


def test_delete_reassigning(
    alice: TestClient, tree: dict[str, dict[str, Any]], used_food: int
) -> None:
    response = alice.delete(
        f"{API}/categories/{tree['home']['id']}",
        params={"reassign_to": tree["food"]["id"]},
    )
    assert response.status_code == 204
    transaction = alice.get(f"{API}/transactions/{used_food}").json()
    assert transaction["splits"][1]["category_id"] == tree["food"]["id"]


def test_delete_uncategorizing(
    alice: TestClient, tree: dict[str, dict[str, Any]], used_food: int
) -> None:
    response = alice.delete(
        f"{API}/categories/{tree['home']['id']}", params={"uncategorize": True}
    )
    assert response.status_code == 204
    transaction = alice.get(f"{API}/transactions/{used_food}").json()
    assert transaction["splits"][1]["category_id"] is None


def test_delete_with_contradicting_options(
    alice: TestClient, tree: dict[str, dict[str, Any]]
) -> None:
    response = alice.delete(
        f"{API}/categories/{tree['home']['id']}",
        params={"uncategorize": True, "reassign_to": tree["food"]["id"]},
    )
    assert response.status_code == 422


def test_delete_unused(alice: TestClient, tree: dict[str, dict[str, Any]]) -> None:
    url = f"{API}/categories/{tree['home']['id']}"
    assert alice.delete(url).status_code == 204
    assert alice.get(url).status_code == 404
