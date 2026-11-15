from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_tests.helpers import API, create_account, create_category


@pytest.fixture
def setup(alice: TestClient) -> dict[str, int]:
    return {
        "checking": create_account(alice, "Checking", opening_balance=100000)["id"],
        "savings": create_account(alice, "Savings", "savings")["id"],
        "food": create_category(alice, "Food")["id"],
        "salary": create_category(alice, "Salary")["id"],
    }


def post(api: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = api.post(f"{API}/transactions{path}", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_record_expense(alice: TestClient, setup: dict[str, int]) -> None:
    expense = post(
        alice,
        "/expense",
        {
            "date": "2025-01-03",
            "amount": 2550,
            "account_id": setup["checking"],
            "category_id": setup["food"],
            "description": "Supermarket",
        },
    )
    assert expense["kind"] == "expense"
    assert expense["net_amount"] == -2550
    assert expense["description"] == "Supermarket"
    assert expense["splits"] == [
        {
            "type": "account",
            "account_id": setup["checking"],
            "amount": -2550,
            "memo": None,
            "security_id": None,
            "quantity": None,
        },
        {
            "type": "external",
            "amount": -2550,
            "category_id": setup["food"],
            "memo": None,
        },
    ]


def test_record_income_and_transfer(alice: TestClient, setup: dict[str, int]) -> None:
    income = post(
        alice,
        "/income",
        {
            "date": "2025-01-27",
            "amount": 250000,
            "account_id": setup["checking"],
            "category_id": setup["salary"],
        },
    )
    assert income["kind"] == "income"
    transfer = post(
        alice,
        "/transfer",
        {
            "date": "2025-01-28",
            "amount": 50000,
            "from_account_id": setup["checking"],
            "to_account_id": setup["savings"],
        },
    )
    assert transfer["kind"] == "transfer"
    assert transfer["net_amount"] == 0


def test_expense_amount_must_be_positive(
    alice: TestClient, setup: dict[str, int]
) -> None:
    response = alice.post(
        f"{API}/transactions/expense",
        json={"date": "2025-01-03", "amount": -5, "account_id": setup["checking"]},
    )
    assert response.status_code == 422


def test_create_with_splits(alice: TestClient, setup: dict[str, int]) -> None:
    created = post(
        alice,
        "",
        {
            "date": "2025-02-01",
            "description": "Mixed receipt",
            "notes": "split",
            "splits": [
                {"type": "account", "account_id": setup["checking"], "amount": -100},
                {"type": "external", "amount": -60, "category_id": setup["food"]},
                {"type": "external", "amount": -40, "memo": "misc"},
            ],
        },
    )
    assert [s["type"] for s in created["splits"]] == ["account", "external", "external"]
    assert created["splits"][2]["memo"] == "misc"
    assert created["notes"] == "split"


def test_unbalanced_splits(alice: TestClient, setup: dict[str, int]) -> None:
    response = alice.post(
        f"{API}/transactions",
        json={
            "date": "2025-02-01",
            "splits": [
                {"type": "account", "account_id": setup["checking"], "amount": -100},
                {"type": "external", "amount": -60},
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_split_type_is_required(alice: TestClient, setup: dict[str, int]) -> None:
    response = alice.post(
        f"{API}/transactions",
        json={"date": "2025-02-01", "splits": [{"amount": -60}]},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


@pytest.mark.parametrize(
    ("change", "loc"),
    [
        ({"splits": []}, ["body", "splits"]),
        ({"splits": [{"type": "external", "amount": -1}] * 101}, ["body", "splits"]),
        ({"amount": 10**15 + 1}, ["body", "splits", 0, "account", "amount"]),
        ({"amount": 2**63}, ["body", "splits", 0, "account", "amount"]),
        ({"date": 0}, ["body", "date"]),
        ({"notes": "n" * 2001}, ["body", "notes"]),
        ({"description": "d" * 2001}, ["body", "description"]),
        ({"memo": "m" * 501}, ["body", "splits", 0, "account", "memo"]),
    ],
)
def test_limits_are_part_of_the_schema(
    alice: TestClient, setup: dict[str, int], change: dict[str, Any], loc: list[Any]
) -> None:
    amount = change.pop("amount", -100)
    memo = change.pop("memo", None)
    body = {
        "date": "2025-02-01",
        "splits": [
            {
                "type": "account",
                "account_id": setup["checking"],
                "amount": amount,
                "memo": memo,
            },
            {"type": "external", "amount": amount},
        ],
        **change,
    }
    response = alice.post(f"{API}/transactions", json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert response.json()["errors"][0]["loc"][: len(loc)] == loc


def test_largest_amount_is_accepted(alice: TestClient, setup: dict[str, int]) -> None:
    income = post(
        alice,
        "/income",
        {"date": "2025-01-01", "amount": 10**15, "account_id": setup["checking"]},
    )
    assert income["net_amount"] == 10**15


def test_fields_that_cannot_be_cleared_reject_null(
    alice: TestClient, setup: dict[str, int]
) -> None:
    created = post(
        alice,
        "/expense",
        {"date": "2025-01-03", "amount": 1000, "account_id": setup["checking"]},
    )
    url = f"{API}/transactions/{created['id']}"
    for field in ("date", "splits"):
        response = alice.patch(url, json={field: None})
        assert response.status_code == 422
        assert response.json()["errors"][0]["loc"] == ["body", field]
    assert alice.patch(url, json={"notes": None}).status_code == 200


def test_get_update_delete(alice: TestClient, setup: dict[str, int]) -> None:
    created = post(
        alice,
        "/expense",
        {"date": "2025-01-03", "amount": 1000, "account_id": setup["checking"]},
    )
    url = f"{API}/transactions/{created['id']}"
    assert alice.get(url).json() == created

    updated = alice.patch(url, json={"description": "Lunch"}).json()
    assert updated["description"] == "Lunch"
    assert updated["date"] == "2025-01-03"

    resplit = alice.patch(
        url,
        json={
            "date": "2025-01-04",
            "splits": [
                {"type": "account", "account_id": setup["checking"], "amount": -1200},
                {"type": "external", "amount": -1200, "category_id": setup["food"]},
            ],
        },
    ).json()
    assert resplit["date"] == "2025-01-04"
    assert resplit["net_amount"] == -1200
    assert resplit["description"] == "Lunch"

    assert alice.delete(url).status_code == 204
    assert alice.get(url).status_code == 404


def test_search(alice: TestClient, setup: dict[str, int]) -> None:
    for day, amount, text in (
        ("2025-01-01", 100, "Bakery"),
        ("2025-01-15", 200, "Cinema"),
        ("2025-02-01", 300, "Bakery again"),
    ):
        post(
            alice,
            "/expense",
            {
                "date": day,
                "amount": amount,
                "account_id": setup["checking"],
                "description": text,
            },
        )

    def search(**params: Any) -> list[str]:
        response = alice.get(f"{API}/transactions", params=params)
        assert response.status_code == 200, response.text
        return [t["description"] for t in response.json()]

    assert search() == ["Bakery", "Cinema", "Bakery again"]
    assert search(text="bakery") == ["Bakery", "Bakery again"]
    assert search(start="2025-01-10", end="2025-01-31") == ["Cinema"]
    assert search(newest_first=True, limit=2) == ["Bakery again", "Cinema"]
    assert search(limit=1, offset=1) == ["Cinema"]
    assert search(account_id=setup["savings"]) == []
    assert search(uncategorized=True)[0] == "Bakery"
    assert alice.get(f"{API}/transactions", params={"limit": 0}).status_code == 422

    dates = alice.get(
        f"{API}/transactions/dates",
        params={"start": "2025-01-01", "end": "2025-01-31"},
    ).json()
    assert dates == ["2025-01-01", "2025-01-15"]


def test_category_filter(alice: TestClient, setup: dict[str, int]) -> None:
    post(
        alice,
        "/expense",
        {
            "date": "2025-01-03",
            "amount": 100,
            "account_id": setup["checking"],
            "category_id": setup["food"],
        },
    )
    found = alice.get(
        f"{API}/transactions",
        params={"category_id": setup["food"], "include_subcategories": True},
    ).json()
    assert len(found) == 1
