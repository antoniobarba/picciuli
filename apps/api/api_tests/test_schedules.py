from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_tests.helpers import API, create_account, create_category


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _splits(account_id: int, amount: int, category_id: int | None = None) -> list[Any]:
    return [
        {"type": "account", "account_id": account_id, "amount": amount},
        {"type": "external", "amount": amount, "category_id": category_id},
    ]


@pytest.fixture
def ids(alice: TestClient) -> dict[str, int]:
    return {
        "checking": create_account(alice, "Checking")["id"],
        "rent": create_category(alice, "Rent")["id"],
    }


def create_schedule(api: TestClient, **body: Any) -> dict[str, Any]:
    response = api.post(f"{API}/schedules", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_crud(alice: TestClient, ids: dict[str, int]) -> None:
    schedule = create_schedule(
        alice,
        start="2025-01-31",
        splits=_splits(ids["checking"], -80000, ids["rent"]),
        description="Rent",
    )
    assert schedule == {
        "id": schedule["id"],
        "description": "Rent",
        "notes": None,
        "splits": [
            {
                "type": "account",
                "account_id": ids["checking"],
                "amount": -80000,
                "memo": None,
                "security_id": None,
                "quantity": None,
            },
            {
                "type": "external",
                "amount": -80000,
                "category_id": ids["rent"],
                "memo": None,
            },
        ],
        "frequency": "monthly",
        "every": 1,
        "day_of_month": 31,
        "next_date": "2025-01-31",
        "end": None,
        "remaining": None,
        "mode": "auto",
        "paused": False,
        "last_error": None,
        "kind": "expense",
        "net_amount": -80000,
        "is_finished": False,
        "debt": None,
    }
    url = f"{API}/schedules/{schedule['id']}"
    assert alice.get(url).json() == schedule
    assert alice.get(f"{API}/schedules").json() == [schedule]
    changed = alice.patch(
        url, json={"frequency": "weekly", "every": 2, "paused": True, "end": None}
    ).json()
    assert (changed["frequency"], changed["day_of_month"], changed["paused"]) == (
        "weekly",
        None,
        True,
    )
    assert alice.patch(url, json={"next_date": None}).status_code == 422
    assert alice.delete(url).status_code == 204
    assert alice.get(url).status_code == 404


def test_invalid_bodies(alice: TestClient, ids: dict[str, int]) -> None:
    splits = _splits(ids["checking"], -100)
    for body, status in (
        ({"start": "2025-01-01", "splits": splits, "every": 0}, 422),
        ({"start": "2025-01-01", "splits": splits, "frequency": "hourly"}, 422),
        ({"start": "2025-01-01", "splits": splits, "day_of_month": 32}, 422),
        ({"start": "2025-01-01", "splits": [splits[0]]}, 422),
        ({"start": "2025-01-01", "splits": _splits(999, -1)}, 404),
    ):
        assert alice.post(f"{API}/schedules", json=body).status_code == status, body


def test_occurrences_post_and_skip(alice: TestClient, ids: dict[str, int]) -> None:
    bill = create_schedule(
        alice,
        start="2025-01-10",
        splits=_splits(ids["checking"], -5000),
        mode="confirm",
        description="Power",
    )
    found = alice.get(
        f"{API}/schedules/occurrences",
        params={"start": "2025-01-01", "end": "2025-03-31"},
    ).json()
    assert found == [
        {"schedule_id": bill["id"], "date": day, "amount": None, "splits": None}
        for day in ("2025-01-10", "2025-02-10", "2025-03-10")
    ]
    too_long = alice.get(
        f"{API}/schedules/occurrences",
        params={"start": "2025-01-01", "end": "2030-01-01"},
    )
    assert too_long.status_code == 422

    posted = alice.post(
        f"{API}/schedules/{bill['id']}/post",
        json={"date": "2025-01-12", "splits": _splits(ids["checking"], -6230)},
    )
    assert posted.status_code == 201, posted.text
    transaction = posted.json()
    assert (transaction["date"], transaction["net_amount"]) == ("2025-01-12", -6230)
    assert (transaction["description"], transaction["schedule_id"]) == (
        "Power",
        bill["id"],
    )
    listed = alice.get(f"{API}/transactions").json()
    assert [t["schedule_id"] for t in listed] == [bill["id"]]

    skipped = alice.post(f"{API}/schedules/{bill['id']}/skip").json()
    assert skipped["next_date"] == "2025-03-10"


def test_catch_up(alice: TestClient, ids: dict[str, int]) -> None:
    today = _today()
    start = (today - dt.timedelta(days=14)).isoformat()
    daily = create_schedule(
        alice, start=start, splits=_splits(ids["checking"], -100), frequency="weekly"
    )
    confirm = create_schedule(
        alice,
        start=start,
        splits=_splits(ids["checking"], -100),
        frequency="weekly",
        mode="confirm",
    )
    response = alice.post(
        f"{API}/schedules/catch-up", json={"today": today.isoformat()}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert [t["schedule_id"] for t in result["posted"]] == [daily["id"]] * 3
    assert [o["schedule_id"] for o in result["due"]] == [confirm["id"]] * 3
    assert result["failed"] == []
    # New books start monthly periods on day 1: the current one is created.
    (period,) = result["periods"]
    assert period["start"] <= today.isoformat() <= period["end"]

    again = alice.post(f"{API}/schedules/catch-up", json={"today": today.isoformat()})
    assert (again.json()["posted"], again.json()["periods"]) == ([], [])


@pytest.mark.parametrize("days", [-2, 2, 400])
def test_catch_up_only_accepts_the_current_day(alice: TestClient, days: int) -> None:
    day = (_today() + dt.timedelta(days=days)).isoformat()
    response = alice.post(f"{API}/schedules/catch-up", json={"today": day})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_monthly_period_settings_and_regeneration(alice: TestClient) -> None:
    settings = alice.get(f"{API}/settings").json()
    assert (settings["period_start_day"], settings["period_weekend_shift"]) == (1, True)
    alice.post(f"{API}/periods", json={"start": "2025-01-01", "end": "2025-01-31"})
    updated = alice.patch(
        f"{API}/settings",
        json={"period_start_day": 27, "period_weekend_shift": False},
    ).json()
    assert (updated["period_start_day"], updated["period_weekend_shift"]) == (
        27,
        False,
    )
    preview = alice.get(
        f"{API}/periods/regenerate", params={"today": "2025-02-10"}
    ).json()
    assert [(c["kind"], c["name"], c["start"], c["end"]) for c in preview] == [
        ("update", "January 2025", "2024-12-27", "2025-01-26"),
        ("create", "February 2025", "2025-01-27", "2025-02-26"),
    ]
    assert preview[0]["period"]["name"] == "January 2025"
    applied = alice.post(
        f"{API}/periods/regenerate", json={"today": "2025-02-10"}
    ).json()
    assert applied == preview
    assert len(alice.get(f"{API}/periods").json()) == 2
    off = alice.patch(f"{API}/settings", json={"period_start_day": None}).json()
    assert off["period_start_day"] is None
    refused = alice.post(f"{API}/periods/regenerate", json={"today": "2025-02-10"})
    assert refused.status_code == 422
    assert (
        alice.patch(f"{API}/settings", json={"period_weekend_shift": None}).status_code
        == 422
    )


def test_schedules_are_private(
    alice: TestClient, bob: TestClient, ids: dict[str, int]
) -> None:
    schedule = create_schedule(
        alice, start="2025-01-01", splits=_splits(ids["checking"], -100)
    )
    assert bob.get(f"{API}/schedules").json() == []
    assert bob.get(f"{API}/schedules/{schedule['id']}").status_code == 404
    assert (
        bob.post(f"{API}/schedules/{schedule['id']}/post", json={}).status_code == 404
    )
