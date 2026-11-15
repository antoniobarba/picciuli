from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_tests.helpers import API, create_account, create_category


def create_period(api: TestClient, **body: Any) -> dict[str, Any]:
    response = api.post(f"{API}/periods", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


class TestPeriods:
    def test_crud(self, alice: TestClient) -> None:
        period = create_period(
            alice, start="2025-01-01", end="2025-01-31", name="January"
        )
        assert period == {
            "id": period["id"],
            "name": "January",
            "start": "2025-01-01",
            "end": "2025-01-31",
        }
        url = f"{API}/periods/{period['id']}"
        assert alice.get(url).json() == period
        assert alice.get(f"{API}/periods").json() == [period]
        renamed = alice.patch(url, json={"name": "Jan", "end": None}).json()
        assert (renamed["name"], renamed["end"]) == ("Jan", None)
        assert alice.delete(url).status_code == 204
        assert alice.get(url).status_code == 404

    def test_open_ended_periods_close_each_other(self, alice: TestClient) -> None:
        first = create_period(alice, start="2025-01-01")
        create_period(alice, start="2025-02-01")
        first = alice.get(f"{API}/periods/{first['id']}").json()
        assert first["end"] == "2025-01-31"

    def test_periods_on_a_day(self, alice: TestClient) -> None:
        create_period(alice, start="2025-01-01", end="2025-01-31", name="January")
        create_period(alice, start="2025-01-20", end="2025-02-10", name="Holiday")
        on = alice.get(f"{API}/periods", params={"on": "2025-01-25"}).json()
        assert sorted(p["name"] for p in on) == ["Holiday", "January"]
        on = alice.get(f"{API}/periods", params={"on": "2025-02-05"}).json()
        assert [p["name"] for p in on] == ["Holiday"]

    def test_end_before_start(self, alice: TestClient) -> None:
        response = alice.post(
            f"{API}/periods", json={"start": "2025-02-01", "end": "2025-01-01"}
        )
        assert response.status_code == 422


@pytest.fixture
def january(alice: TestClient) -> dict[str, int]:
    checking = create_account(alice, "Checking", opening_balance=100000)
    food = create_category(alice, "Food")
    groceries = create_category(alice, "Groceries", parent_id=food["id"])
    salary = create_category(alice, "Salary")
    period = create_period(alice, start="2025-01-01", end="2025-01-31")
    for path, body in (
        ("expense", {"amount": 3000, "category_id": groceries["id"]}),
        ("expense", {"amount": 500}),
        ("income", {"amount": 200000, "category_id": salary["id"]}),
    ):
        response = alice.post(
            f"{API}/transactions/{path}",
            json={"date": "2025-01-10", "account_id": checking["id"], **body},
        )
        assert response.status_code == 201
    return {
        "period": period["id"],
        "food": food["id"],
        "groceries": groceries["id"],
        "checking": checking["id"],
    }


def test_summary(alice: TestClient, january: dict[str, int]) -> None:
    summary = alice.get(f"{API}/periods/{january['period']}/summary").json()
    assert summary["income"] == 200000
    assert summary["expenses"] == -3500
    assert summary["net"] == 196500
    assert summary["uncategorized"] == -500
    totals = {
        c["category"]["name"]: (c["amount"], c["total"]) for c in summary["categories"]
    }
    assert totals["Food"] == (0, -3000)
    assert totals["Groceries"] == (-3000, -3000)
    [change] = summary["accounts"]
    assert (change["opening"], change["closing"], change["change"]) == (
        100000,
        296500,
        196500,
    )


class TestBudgets:
    def test_crud_and_report(self, alice: TestClient, january: dict[str, int]) -> None:
        response = alice.post(
            f"{API}/budgets",
            json={
                "category_id": january["food"],
                "period_id": january["period"],
                "amount": 10000,
            },
        )
        assert response.status_code == 201
        budget = response.json()
        url = f"{API}/budgets/{budget['id']}"
        assert alice.get(url).json() == budget
        assert alice.patch(url, json={"amount": 2000}).json()["amount"] == 2000

        report = alice.get(f"{API}/periods/{january['period']}/budget-report").json()
        [line] = report["lines"]
        assert (line["actual"], line["remaining"]) == (-3000, -1000)
        assert line["category"]["name"] == "Food"
        assert report["total_budget"] == 2000
        assert report["total_remaining"] == -1000

        listed = alice.get(f"{API}/budgets", params={"period_id": january["period"]})
        assert [b["id"] for b in listed.json()] == [budget["id"]]
        by_category = alice.get(f"{API}/budgets", params={"category_id": 999})
        assert by_category.json() == []

        assert alice.delete(url).status_code == 204
        assert alice.get(url).status_code == 404

    def test_negative_budget(self, alice: TestClient, january: dict[str, int]) -> None:
        response = alice.post(
            f"{API}/budgets",
            json={
                "category_id": january["food"],
                "period_id": january["period"],
                "amount": -1,
            },
        )
        assert response.status_code == 422

    def test_copy(self, alice: TestClient, january: dict[str, int]) -> None:
        february = create_period(alice, start="2025-02-01", end="2025-02-28")
        for category in ("food", "groceries"):
            alice.post(
                f"{API}/budgets",
                json={
                    "category_id": january[category],
                    "period_id": january["period"],
                    "amount": 5000,
                },
            )
        copied = alice.post(
            f"{API}/budgets/copy",
            json={
                "source_period_id": january["period"],
                "target_period_id": february["id"],
            },
        ).json()
        assert len(copied) == 2
        assert {b["period_id"] for b in copied} == {february["id"]}
