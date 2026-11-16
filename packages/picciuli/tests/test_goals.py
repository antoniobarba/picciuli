from __future__ import annotations

import datetime as dt

import pytest

from picciuli import (
    Account,
    AccountType,
    Book,
    ConflictError,
    GoalPriority,
    GoalStatus,
    NotFoundError,
    SavingsGoal,
    ValidationError,
)

from .conftest import d


def test_an_account_holds_several_independent_goals(
    book: Book, savings: Account
) -> None:
    holiday = book.goals.create(
        savings.id,
        " Holiday ",
        150000,
        saved_amount=20000,
        target_date=d(31, 7),
        priority="high",
    )
    car = book.goals.create(savings.id, "Car", 900000)
    assert holiday == SavingsGoal(
        holiday.id, savings.id, "Holiday", 150000, 20000, d(31, 7), GoalPriority.HIGH
    )
    assert (car.saved_amount, car.target_date, car.priority) == (
        0,
        None,
        GoalPriority.NORMAL,
    )

    book.goals.update(car.id, saved_amount=5000)

    assert book.goals.get(holiday.id) == holiday
    assert book.goals.get(car.id).saved_amount == 5000
    assert book.accounts.balance(savings.id) == 0
    assert book.transactions.list() == []


def test_names_are_unique_within_an_account_only(
    book: Book, checking: Account, savings: Account
) -> None:
    goal = book.goals.create(savings.id, "Emergency", 100)
    book.goals.create(checking.id, "emergency", 100)
    with pytest.raises(ConflictError, match="already has a goal named 'Emergency'"):
        book.goals.create(savings.id, "EMERGENCY", 100)
    other = book.goals.create(savings.id, "Car", 100)
    with pytest.raises(ConflictError):
        book.goals.update(other.id, name="emergency")
    with pytest.raises(ConflictError):
        book.goals.update(goal.id, account_id=checking.id)
    assert book.goals.update(goal.id, name="EMERGENCY").name == "EMERGENCY"


def test_list_orders_by_account_then_priority(
    book: Book, checking: Account, savings: Account
) -> None:
    low = book.goals.create(checking.id, "Low", 1, priority=GoalPriority.LOW)
    normal = book.goals.create(checking.id, "Normal", 1)
    high = book.goals.create(checking.id, "High", 1, priority="high")
    later = book.goals.create(savings.id, "Later", 1, priority="high")
    assert book.goals.list() == [high, normal, low, later]
    assert book.goals.list(account_id=savings.id) == [later]
    book.accounts.move(savings.id, 1)
    assert book.goals.list()[0] == later


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"name": " "}, ValidationError, "cannot be empty"),
        ({"target_amount": 0}, ValidationError, "greater than zero"),
        ({"saved_amount": -1}, ValidationError, "cannot be negative"),
        ({"target_date": dt.datetime(2025, 1, 1)}, ValidationError, "without time"),
        ({"priority": "urgent"}, ValidationError, "invalid priority"),
        ({"account_id": 99}, NotFoundError, "account 99"),
    ],
)
def test_validation(
    book: Book,
    savings: Account,
    kwargs: dict[str, object],
    error: type[Exception],
    message: str,
) -> None:
    args: dict[str, object] = {"account_id": savings.id, "name": "Goal"}
    args["target_amount"] = 100
    args.update(kwargs)
    with pytest.raises(error, match=message):
        book.goals.create(**args)  # type: ignore[arg-type]
    assert book.goals.list() == []


@pytest.mark.parametrize(
    "kind",
    [
        AccountType.INVESTMENT,
        AccountType.CREDIT_CARD,
        AccountType.LOAN,
        AccountType.MORTGAGE,
        AccountType.OTHER_LIABILITY,
    ],
)
def test_only_cash_like_accounts_hold_goals(
    book: Book, savings: Account, kind: AccountType
) -> None:
    other = book.accounts.create("Other", kind)
    with pytest.raises(ValidationError, match="cannot hold savings goals"):
        book.goals.create(other.id, "Goal", 100)
    goal = book.goals.create(savings.id, "Goal", 100)
    with pytest.raises(ValidationError, match="cannot hold savings goals"):
        book.goals.update(goal.id, account_id=other.id)
    with pytest.raises(ConflictError, match="has savings goals"):
        book.accounts.update(savings.id, type=kind)
    assert book.accounts.get(savings.id).type is AccountType.SAVINGS
    assert book.accounts.update(savings.id, type="cash").type is AccountType.CASH


def test_goals_survive_closing_and_block_deletion(
    book: Book, checking: Account, savings: Account
) -> None:
    goal = book.goals.create(savings.id, "Goal", 100)
    book.accounts.close(savings.id, on=d(1))
    assert book.goals.update(goal.id, saved_amount=50).saved_amount == 50
    with pytest.raises(ConflictError, match="closed"):
        book.goals.create(savings.id, "New", 100)
    moved = book.goals.create(checking.id, "Moved", 100)
    with pytest.raises(ConflictError, match="closed"):
        book.goals.update(moved.id, account_id=savings.id)
    book.accounts.reopen(savings.id)
    with pytest.raises(ConflictError, match="has savings goals"):
        book.accounts.delete(savings.id)
    book.goals.delete(goal.id)
    book.accounts.delete(savings.id)
    with pytest.raises(NotFoundError, match="goal"):
        book.goals.get(goal.id)


def test_monthly_amount_counts_this_month_and_the_target_month(
    book: Book, savings: Account
) -> None:
    book.goals.create(savings.id, "Trip", 10001, target_date=d(10, 1, 2026))
    (account,) = book.goals.report(today=d(30, 11)).accounts
    (trip,) = account.goals
    assert (trip.status, trip.remaining) == (GoalStatus.SCHEDULED, 10001)
    assert (trip.months_left, trip.monthly_amount) == (3, 3334)


@pytest.mark.parametrize(
    ("target", "saved", "status", "months", "monthly"),
    [
        (d(15, 3), 0, GoalStatus.SCHEDULED, 1, 1200),  # due today
        (d(31, 3), 200, GoalStatus.SCHEDULED, 1, 1000),  # later this month
        (d(29, 2, 2028), 0, GoalStatus.SCHEDULED, 36, 34),  # leap day, years ahead
        (d(14, 3), 0, GoalStatus.OVERDUE, None, None),  # yesterday
        (d(1, 1), 0, GoalStatus.OVERDUE, None, None),
        (None, 0, GoalStatus.UNDATED, None, None),
        (d(1, 1), 1200, GoalStatus.REACHED, None, 0),
        (None, 5000, GoalStatus.REACHED, None, 0),  # saved beyond the target
    ],
)
def test_goal_status(
    book: Book,
    savings: Account,
    target: dt.date | None,
    saved: int,
    status: GoalStatus,
    months: int | None,
    monthly: int | None,
) -> None:
    book.goals.create(savings.id, "Goal", 1200, saved_amount=saved, target_date=target)
    (goal,) = book.goals.report(today=d(15, 3)).accounts[0].goals
    assert (goal.status, goal.months_left, goal.monthly_amount) == (
        status,
        months,
        monthly,
    )
    assert goal.remaining == max(1200 - saved, 0)


def test_report_compares_assigned_money_with_the_balance(
    book: Book, checking: Account, savings: Account
) -> None:
    book.transactions.record_transfer(
        d(1), 30000, from_account_id=checking.id, to_account_id=savings.id
    )
    book.transactions.record_transfer(
        d(20), 50000, from_account_id=checking.id, to_account_id=savings.id
    )
    book.goals.create(savings.id, "A", 50000, saved_amount=20000)
    b = book.goals.create(savings.id, "B", 50000, saved_amount=25000)

    (account,) = book.goals.report(today=d(10)).accounts
    assert account.account == savings
    assert (account.balance, account.assigned) == (30000, 45000)
    assert (account.unassigned, account.shortfall) == (0, 15000)

    (account,) = book.goals.report(today=d(20)).accounts
    assert (account.balance, account.unassigned, account.shortfall) == (
        80000,
        35000,
        0,
    )

    book.goals.delete(b.id)
    (account,) = book.goals.report(today=d(10)).accounts
    assert (account.unassigned, account.shortfall) == (10000, 0)


def test_report_counts_a_negative_balance_as_nothing_available(
    book: Book, checking: Account
) -> None:
    book.transactions.record_expense(d(1), 700, account_id=checking.id)
    book.goals.create(checking.id, "Buffer", 1000, saved_amount=300)
    (account,) = book.goals.report(today=d(2)).accounts
    assert (account.balance, account.unassigned, account.shortfall) == (-700, 0, 300)


def test_report_lists_only_accounts_with_goals(book: Book, checking: Account) -> None:
    report = book.goals.report(today=d(1))
    assert (report.today, report.accounts) == (d(1), ())
