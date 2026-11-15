from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest

from picciuli import (
    Account,
    AccountSplit,
    AccountType,
    Book,
    Category,
    ConflictError,
    CostMethod,
    ExternalSplit,
    Security,
    SecurityKind,
    ValidationError,
)
from picciuli_tui.formatting import MoneyFormat
from picciuli_tui.forms import (
    AccountDraft,
    EntryKind,
    InputError,
    LineDraft,
    SecurityDraft,
    TradeDraft,
    TransactionDraft,
    account_target,
    category_in_use,
    category_target,
    draft_from_transaction,
    line_splits,
    line_totals,
    move_category,
    parse_date,
    parse_decimal,
    parse_price,
    parse_quantity,
    save_account,
    save_budget,
    save_buy,
    save_category,
    save_period,
    save_price,
    save_security,
    save_sell,
    save_settings,
    save_transaction,
    simple_lines,
    trade_from_transaction,
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
        LineDraft(),
    ]
    incomplete = TransactionDraft(EntryKind.EXPENSE, account_id=checking.id)
    assert simple_lines(incomplete, money) == [
        LineDraft(account_target(checking.id)),
        LineDraft(),
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


def test_save_settings_for_investments(book: Book) -> None:
    save_settings(
        book,
        currency="€",
        digits="2",
        currency_code=" eur ",
        cost_method=CostMethod.FIFO,
        price_provider="yahoo",
    )
    settings = book.settings.get()
    assert (settings.currency_code, settings.cost_method) == ("EUR", CostMethod.FIFO)
    save_settings(book, currency="€", digits="2", currency_code="")
    assert book.settings.get().currency_code is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.5", Decimal("1.5")),
        ("1,5", Decimal("1.5")),
        ("1,234.5", Decimal("1234.5")),
        ("1.234,5", Decimal("1234.5")),
        (" 2 ", Decimal(2)),
    ],
)
def test_parse_decimal(text: str, expected: Decimal) -> None:
    assert parse_decimal(text, "quantity") == expected


@pytest.mark.parametrize("text", ["", "abc", "inf", "1,2,3"])
def test_parse_decimal_rejects(text: str) -> None:
    with pytest.raises(InputError):
        parse_decimal(text, "quantity")


def test_quantities_and_prices_must_be_positive() -> None:
    assert parse_quantity("-2", signed=True) == -2
    for text in ("0", "-1"):
        with pytest.raises(InputError):
            parse_quantity(text)
        with pytest.raises(InputError):
            parse_price(text)
    assert parse_price("169,86") == Decimal("169.86")


@pytest.fixture
def broker(book: Book) -> Account:
    return book.accounts.create("Broker", AccountType.INVESTMENT)


@pytest.fixture
def etf(book: Book) -> Security:
    return book.securities.create("ETF", currency="USD", symbol="E")


def test_security_drafts(book: Book) -> None:
    with pytest.raises(InputError, match="currency"):
        save_security(book, SecurityDraft(name="X"))
    draft = SecurityDraft(name="X", symbol=" X.MI ", isin="", currency="eur")
    created = save_security(book, draft)
    assert (created.symbol, created.isin, created.currency) == ("X.MI", None, "EUR")
    edited = SecurityDraft.of(created)
    edited.notes = "note"
    edited.kind = SecurityKind.BOND
    updated = save_security(book, edited, security_id=created.id)
    assert (updated.notes, updated.kind) == ("note", SecurityKind.BOND)


def test_buy_sell_and_price(
    book: Book, money: MoneyFormat, checking: Account, broker: Account, etf: Security
) -> None:
    draft = TradeDraft(
        date="1",
        account_id=broker.id,
        security_id=etf.id,
        quantity="2",
        amount="70",
        other_account_id=checking.id,
        fee="1",
    )
    bought = save_buy(book, draft, money, today=TODAY)
    assert bought.date == dt.date(2025, 3, 1)
    assert book.accounts.balance(checking.id) == -7100
    sell = TradeDraft(
        date="2",
        account_id=broker.id,
        security_id=etf.id,
        quantity="1,5",
        amount="60",
        other_account_id=0,
        tax="2",
    )
    sold = save_sell(book, sell, money, today=TODAY)
    assert sold.net_amount == 6000 - 5250 - 200
    with pytest.raises(InputError, match="negative"):
        save_sell(
            book, TradeDraft(**{**sell.__dict__, "fee": "-1"}), money, today=TODAY
        )
    with pytest.raises(InputError, match="security"):
        save_buy(book, TradeDraft(date="1", account_id=broker.id), money, today=TODAY)
    price = save_price(book, etf.id, date="today", price="35.5", today=TODAY)
    assert (price.date, price.price) == (TODAY, Decimal("35.5"))


def test_read_and_update_recorded_trades(
    book: Book,
    money: MoneyFormat,
    checking: Account,
    broker: Account,
    etf: Security,
    food: Category,
) -> None:
    gains = book.categories.create("Gains")
    taxes = book.categories.create("Taxes")
    bought = book.investments.record_buy(
        TODAY,
        account_id=broker.id,
        security_id=etf.id,
        quantity=Decimal("1.5"),
        cost=3500,
        from_account_id=checking.id,
        fee=100,
        fee_category_id=food.id,
        description="Buy ETF",
        notes="Monthly purchase",
    )
    parsed_buy = trade_from_transaction(bought, money)
    assert parsed_buy == (
        False,
        TradeDraft(
            date=TODAY.isoformat(),
            account_id=broker.id,
            security_id=etf.id,
            quantity="1.5",
            amount="35.00",
            other_account_id=checking.id,
            fee="1.00",
            tax="",
            category_id=food.id,
            fee_category_id=food.id,
            tax_category_id=None,
            description="Buy ETF",
            notes="Monthly purchase",
        ),
    )
    assert trade_from_transaction(replace(bought, trade=None), money) is None
    edited_buy = save_buy(
        book,
        TradeDraft(
            **{
                **parsed_buy[1].__dict__,
                "quantity": "2",
                "amount": "40.00",
                "fee": "2.00",
                "description": "Edited buy",
            }
        ),
        money,
        today=TODAY,
        transaction_id=bought.id,
    )
    assert edited_buy.id == bought.id
    assert edited_buy.description == "Edited buy"
    assert edited_buy.notes == "Monthly purchase"
    assert [s.quantity for s in edited_buy.account_splits if s.quantity] == [Decimal(2)]

    sold = book.investments.record_sell(
        TODAY + dt.timedelta(days=1),
        account_id=broker.id,
        security_id=etf.id,
        quantity=1,
        proceeds=5000,
        to_account_id=checking.id,
        fee=100,
        fee_category_id=food.id,
        tax=50,
        tax_category_id=taxes.id,
        gain_category_id=gains.id,
        description="Sell ETF",
    )
    parsed_sell = trade_from_transaction(sold, money)
    assert parsed_sell == (
        True,
        TradeDraft(
            date=(TODAY + dt.timedelta(days=1)).isoformat(),
            account_id=broker.id,
            security_id=etf.id,
            quantity="1",
            amount="50.00",
            other_account_id=checking.id,
            fee="1.00",
            tax="0.50",
            category_id=gains.id,
            fee_category_id=food.id,
            tax_category_id=taxes.id,
            description="Sell ETF",
            notes="",
        ),
    )
    edited_sell = save_sell(
        book,
        TradeDraft(
            **{
                **parsed_sell[1].__dict__,
                "quantity": "0.5",
                "amount": "30.00",
            }
        ),
        money,
        today=TODAY,
        transaction_id=sold.id,
    )
    assert edited_sell.id == sold.id
    assert [s.quantity for s in edited_sell.account_splits if s.quantity] == [
        Decimal("-0.5")
    ]
    assert {s.memo: s.category_id for s in edited_sell.external_splits} == {
        "Realized gain": gains.id,
        "Fee": food.id,
        "Tax": taxes.id,
    }


def test_transactions_without_a_trade_use_the_split_editor(
    book: Book, money: MoneyFormat, broker: Account, etf: Security, food: Category
) -> None:
    book.investments.record_buy(
        TODAY, account_id=broker.id, security_id=etf.id, quantity=1, cost=14361
    )
    sold = book.transactions.create(
        TODAY,
        [
            AccountSplit(broker.id, -14361, security_id=etf.id, quantity=Decimal(-1)),
            AccountSplit(broker.id, 14151),
            ExternalSplit(-210, food.id, "Realized gain"),
        ],
    )
    assert trade_from_transaction(sold, money) is None


def test_share_transaction_draft_preserves_share_quantity(
    book: Book, money: MoneyFormat, checking: Account, broker: Account, etf: Security
) -> None:
    bought = book.investments.record_buy(
        TODAY,
        account_id=broker.id,
        security_id=etf.id,
        quantity=Decimal("1.5"),
        cost=3500,
        from_account_id=checking.id,
    )
    draft = draft_from_transaction(bought, money)
    assert draft.kind is EntryKind.SPLIT
    assert draft.lines[0] == LineDraft(
        account_target(broker.id), "35.00", "", etf.id, "1.5"
    )
    draft.description = "Edited"
    saved = save_transaction(book, draft, money, today=TODAY, transaction_id=bought.id)
    assert saved.splits == bought.splits
    assert saved.description == "Edited"
    # A zero amount is fine when shares move (a stock split).
    split = [LineDraft(account_target(broker.id), "0", "", etf.id, "3")]
    assert line_splits(split, money) == [
        AccountSplit(broker.id, 0, security_id=etf.id, quantity=Decimal(3))
    ]
