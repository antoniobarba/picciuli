from __future__ import annotations

from fastapi.testclient import TestClient

from api_tests.helpers import API, create_account, create_category

HISTORY = f"{API}/reports/history"


def test_history_by_month_and_by_period(alice: TestClient) -> None:
    checking = create_account(alice, "Checking", opening_balance=50000)
    food = create_category(alice)
    alice.post(
        f"{API}/transactions/expense",
        json={
            "date": "2025-02-10",
            "amount": 2000,
            "account_id": checking["id"],
            "category_id": food["id"],
        },
    )
    period = alice.post(f"{API}/periods", json={"start": "2025-02-01"}).json()

    months = alice.get(HISTORY, params={"count": 2, "today": "2025-02-15"})
    assert months.status_code == 200, months.text
    jan, feb = months.json()
    assert jan["start"] == "2025-01-01"
    assert jan["flows"] == []
    assert feb == {
        "start": "2025-02-01",
        "end": "2025-02-15",
        "period_id": None,
        "partial": True,
        "income": 0,
        "expenses": -2000,
        "flows": [{"category_id": food["id"], "amount": -2000}],
        "balances": [{"account_id": checking["id"], "balance": 48000, "value": 48000}],
        "assets": 48000,
        "liabilities": 0,
        "net_worth": 48000,
    }

    periods = alice.get(HISTORY, params={"by": "period", "today": "2025-02-15"})
    assert [(p["period_id"], p["expenses"]) for p in periods.json()] == [
        (period["id"], -2000)
    ]
    offset = alice.get(HISTORY, params={"count": 1, "offset": 1, "today": "2025-02-15"})
    assert offset.json()[0]["start"] == "2025-01-01"


def test_history_validates_parameters(alice: TestClient) -> None:
    for params in ({"count": 0}, {"count": 121}, {"offset": -1}, {"by": "week"}):
        assert alice.get(HISTORY, params=params).status_code == 422
