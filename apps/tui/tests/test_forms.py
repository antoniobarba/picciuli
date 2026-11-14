from __future__ import annotations

import datetime as dt

import pytest

from picciuli import (
    Account,
    AccountSplit,
    AccountType,
    Book,
    Category,
    ConflictError,
    ExternalSplit,
    ValidationError,
)
from picciuli_tui.formatting import MoneyFormat
from picciuli_tui.forms import (
    AccountDraft,
    EntryKind,
    InputError,
    LineDraft,
    TransactionDraft,
    account_target,
    category_in_use,
    category_target,
    draft_from_transaction,
    line_splits,
    line_totals,
    move_category,
    parse_date,
    save_account,
    save_budget,
    save_category,
    save_period,
    save_settings,
    save_transaction,
    simple_lines,
)

TODAY = dt.date(2025, 3, 12)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2025-02-03", dt.date(2025, 2, 3)),
        (" 3/2/2025 ", dt.date(2025, 2, 3)),
        ("3.2.25", dt.date(2025, 2, 3)),
        ("3/2", dt.date(2025, 2, 3)),
        ("5", dt.date(2025, 3, 5)),
        ("Today", TODAY),
        ("+1", dt.date(2025, 3, 13)),
        ("-12", dt.date(2025, 2, 28)),
    ],
)
def test_parse_date(text: str, expected: dt.date) -> None:
    assert parse_date(text, today=TODAY) == expected


@pytest.mark.parametrize(
    "text", ["", "  ", "2025-02-30", "32", "1/2/3/4", "soon", "+x"]
)
def test_parse_date_rejects(text: str) -> None:
    with pytest.raises(InputError):
        parse_date(text, today=TODAY)


# Transactions


def test_save_simple_kinds(
    book: Book, money: MoneyFormat, checking: Account, savings: Account, food: Category
) -> None:
    expense = save_transaction(
        book,
        TransactionDraft(
            EntryKind.EXPENSE, "2025-03-01", " Shop ", "", "12.50", checking.id, food.id
        ),
        money,
        today=TODAY,
    )
    assert expense.splits == (
        AccountSplit(checking.id, -1250),
        ExternalSplit(-1250, food.id),
    )
    assert expense.description == "Shop"
    assert expense.notes is None
    income = save_transaction(
        book,
        TransactionDraft(
            EntryKind.INCOME, "today", amount="100", account_id=checking.id
        ),
        money,
        today=TODAY,
    )
    assert income.splits == (AccountSplit(checking.id, 10000), ExternalSplit(10000))
    transfer = save_transaction(
        book,
        TransactionDraft(
            EntryKind.TRANSFER,
            "today",
            amount="5",
            account_id=checking.id,
            to_account_id=savings.id,
        ),
        money,
        today=TODAY,
    )
    assert transfer.splits == (
        AccountSplit(checking.id, -500),
        AccountSplit(savings.id, 500),
    )


def test_save_split_and_update(
    book: Book, money: MoneyFormat, checking: Account, food: Category
) -> None:
    draft = TransactionDraft(
        EntryKind.SPLIT,
        "2025-03-01",
        lines=[
            LineDraft(account_target(checking.id), "-100"),
            LineDraft(category_target(food.id), "-60", "fruit"),
            LineDraft(category_target(None), "-40"),
            LineDraft(),
        ],
    )
    created = save_transaction(book, draft, money, today=TODAY)
    assert created.splits == (
        AccountSplit(checking.id, -10000),
        ExternalSplit(-6000, food.id, "fruit"),
        ExternalSplit(-4000, None),
    )
    simple = TransactionDraft(
        EntryKind.EXPENSE, "2025-03-02", "x", "y", "1", checking.id, food.id
    )
    updated = save_transaction(
        book, simple, money, today=TODAY, transaction_id=created.id
    )
    assert updated.id == created.id
    assert updated.date == dt.date(2025, 3, 2)
    assert updated.splits == (
        AccountSplit(checking.id, -100),
        ExternalSplit(-100, food.id),
    )


@pytest.mark.parametrize(
    ("draft", "message"),
    [
        (TransactionDraft(EntryKind.EXPENSE, "today", amount=""), "amount is required"),
        (TransactionDraft(EntryKind.EXPENSE, "today", amount="-1"), "positive"),
        (TransactionDraft(EntryKind.EXPENSE, "today", amount="1"), "choose an account"),
        (
            TransactionDraft(EntryKind.TRANSFER, "today", amount="1", account_id=1),
            "destination",
        ),
        (
            TransactionDraft(
                EntryKind.TRANSFER, "today", amount="1", account_id=1, to_account_id=1
            ),
            "different",
        ),
        (
            TransactionDraft(EntryKind.SPLIT, "today", lines=[LineDraft("", "1")]),
            "account or category",
        ),
        (
            TransactionDraft(EntryKind.SPLIT, "today", lines=[LineDraft("a:1", " ")]),
            "needs an amount",
        ),
        (
            TransactionDraft(EntryKind.SPLIT, "today", lines=[LineDraft("c:1", "0")]),
            "cannot be zero",
        ),
    ],
)
def test_transaction_input_errors(
    book: Book, money: MoneyFormat, draft: TransactionDraft, message: str
) -> None:
    with pytest.raises(InputError, match=message):
        save_transaction(book, draft, money, today=TODAY)


def test_unbalanced_split_is_rejected_by_the_library(
    book: Book, money: MoneyFormat, checking: Account
) -> None:
    draft = TransactionDraft(
        EntryKind.SPLIT,
        "today",
        lines=[LineDraft(account_target(checking.id), "-1"), LineDraft("c:0", "-2")],
    )
    with pytest.raises(ValidationError):
        save_transaction(book, draft, money, today=TODAY)


def test_draft_from_transaction_detects_shapes(
    book: Book, money: MoneyFormat, checking: Account, savings: Account, food: Category
) -> None:
    day = dt.date(2025, 3, 1)
    record = book.transactions
    expense = record.record_expense(
        day, 1250, account_id=checking.id, description="d", notes="n"
    )
    draft = draft_from_transaction(expense, money)
    assert (draft.kind, draft.amount, draft.account_id, draft.category_id) == (
        EntryKind.EXPENSE,
        "12.50",
        checking.id,
        0,
    )
    assert (draft.date, draft.description, draft.notes) == ("2025-03-01", "d", "n")
    income = record.record_income(day, 1, account_id=checking.id, category_id=food.id)
    assert draft_from_transaction(income, money).kind is EntryKind.INCOME
    transfer = record.record_transfer(
        day, 300, from_account_id=savings.id, to_account_id=checking.id
    )
    draft = draft_from_transaction(transfer, money)
    assert (draft.kind, draft.amount, draft.account_id, draft.to_account_id) == (
        EntryKind.TRANSFER,
        "3.00",
        savings.id,
        checking.id,
    )
    with_memo = record.create(
        day, [AccountSplit(checking.id, -5, "memo"), ExternalSplit(-5, food.id)]
    )
    draft = draft_from_transaction(with_memo, money)
    assert draft.kind is EntryKind.SPLIT
    assert draft.lines == [
        LineDraft(account_target(checking.id), "-0.05", "memo"),
        LineDraft(category_target(food.id), "-0.05"),
    ]


def test_line_helpers(money: MoneyFormat, checking: Account, food: Category) -> None:
    lines = [
        LineDraft(account_target(checking.id), "-10"),
        LineDraft(category_target(food.id), "-4"),
        LineDraft("c:0", "oops"),
        LineDraft(),
    ]
    assert line_totals(lines, money) == (-1000, -400)
    with pytest.raises(ValidationError):
        line_splits(lines, money)
    simple = TransactionDraft(
        EntryKind.EXPENSE, amount="2", account_id=checking.id, category_id=food.id
    )
    assert simple_lines(simple, money) == [
        LineDraft(account_target(checking.id), "-2.00"),
        LineDraft(category_target(food.id), "-2.00"),
    ]
    incomplete = TransactionDraft(EntryKind.EXPENSE, account_id=checking.id)
    assert simple_lines(incomplete, money) == [
        LineDraft(account_target(checking.id)),
        LineDraft(),
    ]


# Other entities


def test_save_account_create_and_update(book: Book, money: MoneyFormat) -> None:
    created = save_account(
        book,
        AccountDraft(
            "Mortgage", AccountType.MORTGAGE, "-150,000", "2025-01-01", "", " "
        ),
        money,
        today=TODAY,
    )
    assert (
        created.opening_balance,
        created.opening_date,
        created.goal,
        created.notes,
    ) == (-15_000_000, dt.date(2025, 1, 1), None, None)
    draft = AccountDraft.of(created, money)
    assert draft == AccountDraft(
        "Mortgage", AccountType.MORTGAGE, "-150000.00", "2025-01-01", "", ""
    )
    draft.goal, draft.notes = "0", "home"
    updated = save_account(book, draft, money, today=TODAY, account_id=created.id)
    assert (updated.goal, updated.notes, updated.opening_balance) == (
        0,
        "home",
        -15_000_000,
    )


def test_save_account_keeps_closed_account_editable(
    book: Book, money: MoneyFormat
) -> None:
    account = book.accounts.create("Old", AccountType.CASH)
    closed = book.accounts.close(account.id, on=TODAY)
    draft = AccountDraft.of(closed, money)
    draft.name = "Older"
    assert save_account(book, draft, money, today=TODAY, account_id=closed.id).name == (
        "Older"
    )
    draft.opening_balance = "5"
    with pytest.raises(ConflictError):
        save_account(book, draft, money, today=TODAY, account_id=closed.id)


def test_categories(book: Book, checking: Account) -> None:
    food = save_category(book, name="Food", symbol="", parent_id=0)
    home = save_category(book, name="Home", symbol="H", parent_id=None)
    fruit = save_category(book, name="Fruit", symbol="", parent_id=food.id)
    assert (fruit.parent_id, food.symbol, home.symbol) == (food.id, "FOOD", "H")
    moved = save_category(
        book, name="Fruits", symbol="FR", parent_id=home.id, category_id=fruit.id
    )
    assert (moved.name, moved.symbol, moved.parent_id) == ("Fruits", "FR", home.id)
    renamed = save_category(
        book, name="Foods", symbol="", parent_id=0, category_id=food.id
    )
    assert renamed.name == "Foods"
    assert move_category(book, home, -1).position == 1
    assert move_category(book, book.categories.get(home.id), -1).position == 1
    assert not category_in_use(book, food.id)
    book.transactions.record_expense(
        TODAY, 1, account_id=checking.id, category_id=food.id
    )
    assert category_in_use(book, food.id)


def test_save_period(book: Book) -> None:
    period = save_period(book, name=" ", start="2025-02-27", end="", today=TODAY)
    assert (period.name, period.end) == ("February 2025", None)
    updated = save_period(
        book,
        name="Feb",
        start="2025-02-27",
        end="26/3",
        today=TODAY,
        period_id=period.id,
    )
    assert (updated.name, updated.end) == ("Feb", dt.date(2025, 3, 26))


def test_save_budget(book: Book, money: MoneyFormat, food: Category) -> None:
    period = book.periods.create(TODAY)
    home = book.categories.create("Home")
    save_budget(book, money, category_id=food.id, period_id=period.id, amount="300")
    (budget,) = book.budgets.list(period_id=period.id)
    assert budget.amount == 30000
    save_budget(
        book,
        money,
        category_id=home.id,
        period_id=period.id,
        amount="50",
        budget_id=budget.id,
    )
    assert book.budgets.get(budget.id).category_id == home.id
    with pytest.raises(InputError, match="category"):
        save_budget(book, money, category_id=None, period_id=period.id, amount="1")
    with pytest.raises(InputError, match="amount"):
        save_budget(book, money, category_id=food.id, period_id=period.id, amount="")


def test_save_settings(book: Book) -> None:
    assert save_settings(book, currency=" € ", digits="0") == MoneyFormat("€", 0)
    with pytest.raises(InputError):
        save_settings(book, currency="€", digits="two")
    with pytest.raises(ValidationError):
        save_settings(book, currency="€", digits="9")
