from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from picciuli import (
    UNSET,
    Account,
    AccountClass,
    AccountSplit,
    AccountType,
    Book,
    Category,
    ConflictError,
    ExternalSplit,
    NotFoundError,
    ValidationError,
)
from picciuli.limits import MAX_AMOUNT

from .conftest import d


class TestCreate:
    def test_defaults(self, book: Book) -> None:
        account = book.accounts.create("Checking", AccountType.CHECKING)
        assert account == Account(
            id=account.id,
            name="Checking",
            type=AccountType.CHECKING,
            opening_balance=0,
            opening_date=None,
            goal=None,
            notes=None,
            position=1,
            closed_on=None,
        )
        assert account.account_class is AccountClass.ASSET
        assert not account.is_closed

    def test_all_fields_and_string_type(self, book: Book) -> None:
        account = book.accounts.create(
            "  Mortgage ",
            "mortgage",
            opening_balance=-20_000_000,
            opening_date=d(1),
            goal=0,
            notes="  fixed rate ",
        )
        assert account.name == "Mortgage"
        assert account.type is AccountType.MORTGAGE
        assert account.account_class is AccountClass.LIABILITY
        assert account.opening_balance == -20_000_000
        assert account.opening_date == d(1)
        assert account.goal == 0
        assert account.notes == "fixed rate"

    def test_positions_are_appended(self, book: Book) -> None:
        names = ["A", "B", "C"]
        for name in names:
            book.accounts.create(name, AccountType.CASH)
        assert [(a.name, a.position) for a in book.accounts.list()] == [
            ("A", 1),
            ("B", 2),
            ("C", 3),
        ]

    def test_names_are_unique_case_insensitively(
        self, book: Book, checking: Account
    ) -> None:
        with pytest.raises(ConflictError, match="already exists"):
            book.accounts.create("CHECKING", AccountType.SAVINGS)

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"name": " "}, "cannot be empty"),
            ({"name": 3}, "must be a string"),
            ({"name": "a\nb"}, "printable"),
            ({"type": "wallet"}, "invalid account type"),
            ({"opening_balance": 1.5}, "integer"),
            ({"opening_balance": True}, "integer"),
            ({"opening_date": dt.datetime(2025, 1, 1)}, "without time"),
            ({"goal": "100"}, "integer"),
            ({"notes": 5}, "string or None"),
            ({"opening_balance": MAX_AMOUNT + 1}, "opening balance cannot exceed"),
            ({"opening_balance": -(2**63)}, "opening balance cannot exceed"),
            ({"goal": 2**64}, "goal cannot exceed"),
            ({"name": "n" * 201}, "name cannot exceed 200"),
            ({"notes": "n" * 2001}, "notes cannot exceed 2000"),
        ],
    )
    def test_validation(
        self, book: Book, kwargs: dict[str, object], message: str
    ) -> None:
        args = {"name": "X", "type": AccountType.CASH, **kwargs}
        name, account_type = args.pop("name"), args.pop("type")
        with pytest.raises(ValidationError, match=message):
            book.accounts.create(name, account_type, **args)  # type: ignore[arg-type]


class TestReadAndUpdate:
    def test_get_missing(self, book: Book) -> None:
        with pytest.raises(NotFoundError, match="account 99"):
            book.accounts.get(99)

    def test_update_selected_fields(self, book: Book, checking: Account) -> None:
        updated = book.accounts.update(
            checking.id,
            name="Main",
            type=AccountType.CASH,
            goal=500,
            notes="wallet",
            opening_balance=100,
            opening_date=d(1),
        )
        assert updated.name == "Main"
        assert updated.type is AccountType.CASH
        assert (updated.goal, updated.notes) == (500, "wallet")
        assert (updated.opening_balance, updated.opening_date) == (100, d(1))
        cleared = book.accounts.update(checking.id, goal=None, notes=None)
        assert (cleared.goal, cleared.notes, cleared.name) == (None, None, "Main")

    def test_update_keeps_own_name_but_rejects_other(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        assert book.accounts.update(checking.id, name="checking").name == "checking"
        with pytest.raises(ConflictError):
            book.accounts.update(checking.id, name="SAVINGS")

    def test_opening_date_cannot_follow_transactions(
        self, book: Book, checking: Account
    ) -> None:
        book.transactions.record_income(d(5), 100, account_id=checking.id)
        book.accounts.update(checking.id, opening_date=d(5))
        with pytest.raises(ValidationError, match="before the new opening date"):
            book.accounts.update(checking.id, opening_date=d(6))
        assert book.accounts.update(checking.id, opening_date=None).opening_date is None

    def test_list_filters_closed(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        book.accounts.close(savings.id, on=d(1))
        assert [a.id for a in book.accounts.list()] == [checking.id, savings.id]
        assert [a.id for a in book.accounts.list(include_closed=False)] == [checking.id]

    def test_move(self, book: Book) -> None:
        a, b, c = (book.accounts.create(n, AccountType.CASH) for n in "ABC")
        assert book.accounts.move(c.id, 1).position == 1
        assert [x.name for x in book.accounts.list()] == ["C", "A", "B"]
        book.accounts.move(c.id, 3)
        assert [(x.name, x.position) for x in book.accounts.list()] == [
            ("A", 1),
            ("B", 2),
            ("C", 3),
        ]
        with pytest.raises(ValidationError, match="between 1 and 3"):
            book.accounts.move(a.id, 4)
        with pytest.raises(ValidationError):
            book.accounts.move(b.id, 0)


class TestLifecycle:
    def test_close_and_reopen(self, book: Book, checking: Account) -> None:
        closed = book.accounts.close(checking.id, on=d(10))
        assert closed.closed_on == d(10)
        assert closed.is_closed
        with pytest.raises(ConflictError, match="already closed"):
            book.accounts.close(checking.id)
        assert book.accounts.reopen(checking.id).closed_on is None
        with pytest.raises(ConflictError, match="not closed"):
            book.accounts.reopen(checking.id)

    def test_close_defaults_to_today(self, book: Book, checking: Account) -> None:
        assert book.accounts.close(checking.id).closed_on == dt.date.today()

    def test_close_requires_zero_balance(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        book.transactions.record_income(d(1), 100, account_id=savings.id)
        with pytest.raises(ConflictError, match="must be zero"):
            book.accounts.close(savings.id, on=d(2))
        book.transactions.record_transfer(
            d(2), 100, from_account_id=savings.id, to_account_id=checking.id
        )
        assert book.accounts.close(savings.id, on=d(2)).closed_on == d(2)

    def test_close_date_rules(self, book: Book, checking: Account) -> None:
        book.accounts.update(checking.id, opening_date=d(5))
        with pytest.raises(ValidationError, match="before the opening date"):
            book.accounts.close(checking.id, on=d(4))
        book.transactions.record_income(d(8), 100, account_id=checking.id)
        book.transactions.record_expense(d(9), 100, account_id=checking.id)
        with pytest.raises(ConflictError, match="transactions after"):
            book.accounts.close(checking.id, on=d(8))

    def test_closed_account_rules(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        tx = book.transactions.record_transfer(
            d(1), 100, from_account_id=savings.id, to_account_id=checking.id
        )
        book.transactions.record_transfer(
            d(2), 100, from_account_id=checking.id, to_account_id=savings.id
        )
        book.accounts.close(checking.id, on=d(3))
        with pytest.raises(ConflictError, match="closed"):
            book.transactions.record_income(d(4), 1, account_id=checking.id)
        with pytest.raises(ConflictError, match="closed account"):
            book.transactions.update(tx.id, description="x")
        with pytest.raises(ConflictError, match="closed account"):
            book.transactions.delete(tx.id)
        with pytest.raises(ConflictError, match="reopen"):
            book.accounts.update(checking.id, opening_balance=5)
        assert book.accounts.update(checking.id, name="Old").name == "Old"

    def test_delete_unused_account_renumbers(self, book: Book) -> None:
        _a, b, _c = (book.accounts.create(n, AccountType.CASH) for n in "ABC")
        book.accounts.delete(b.id)
        assert [(x.name, x.position) for x in book.accounts.list()] == [
            ("A", 1),
            ("C", 2),
        ]
        with pytest.raises(NotFoundError):
            book.accounts.get(b.id)

    def test_delete_used_account_is_refused(
        self, book: Book, checking: Account
    ) -> None:
        book.transactions.record_income(d(1), 100, account_id=checking.id)
        with pytest.raises(ConflictError, match="close it instead"):
            book.accounts.delete(checking.id)


class TestBalances:
    def test_balance_as_of(self, book: Book, checking: Account) -> None:
        book.accounts.update(checking.id, opening_balance=1000, opening_date=d(2))
        book.transactions.record_income(d(3), 500, account_id=checking.id)
        book.transactions.record_expense(d(5), 200, account_id=checking.id)
        assert book.accounts.balance(checking.id, as_of=d(1)) == 0
        assert book.accounts.balance(checking.id, as_of=d(2)) == 1000
        assert book.accounts.balance(checking.id, as_of=d(4)) == 1500
        assert book.accounts.balance(checking.id) == 1300
        with pytest.raises(NotFoundError):
            book.accounts.balance(42)

    def test_opening_balance_without_date_always_applies(self, book: Book) -> None:
        account = book.accounts.create("Wallet", AccountType.CASH, opening_balance=700)
        assert book.accounts.balance(account.id, as_of=dt.date(1900, 1, 1)) == 700

    def test_balances_and_closed_accounts(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        book.transactions.record_income(d(1), 300, account_id=checking.id)
        book.accounts.close(savings.id, on=d(10))
        current = book.accounts.balances()
        assert [(b.account.name, b.balance) for b in current] == [("Checking", 300)]
        before_close = book.accounts.balances(as_of=d(9))
        assert [b.account.name for b in before_close] == ["Checking", "Savings"]
        everything = book.accounts.balances(include_closed=True)
        assert [b.account.name for b in everything] == ["Checking", "Savings"]

    def test_net_worth_with_liabilities(
        self, book: Book, checking: Account, card: Account
    ) -> None:
        mortgage = book.accounts.create(
            "Mortgage", AccountType.MORTGAGE, opening_balance=-100_000
        )
        book.transactions.record_income(d(1), 5000, account_id=checking.id)
        book.transactions.record_expense(d(2), 300, account_id=card.id)
        book.transactions.create(
            d(3),
            [
                AccountSplit(checking.id, -1500),
                AccountSplit(mortgage.id, 1200),
                ExternalSplit(-300),
            ],
        )
        worth = book.accounts.net_worth()
        assert (worth.assets, worth.liabilities) == (3500, -100_000 + 1200 - 300)
        assert worth.net_worth == 3500 - 99_100
        early = book.accounts.net_worth(as_of=d(1))
        assert (early.as_of, early.assets, early.liabilities) == (d(1), 5000, -100_000)

    def test_totals_beyond_64_bits_stay_readable(self, tmp_path: Path) -> None:
        """Books written before the amount limit may hold values near 2**63."""
        path = tmp_path / "legacy.db"
        with Book.open(path) as book:
            account = book.accounts.create("Old", AccountType.CHECKING)
            food = book.categories.create("Food")
            period = book.periods.create(d(1), end=d(31))
            for day in (1, 2):
                book.transactions.record_income(d(day), 1, account_id=account.id)
            for day in (3, 4):
                book.transactions.record_expense(
                    d(day), 2, account_id=account.id, category_id=food.id
                )
        top = 2**63 - 1
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE splits SET amount = ? WHERE amount = 1", (top,))
            connection.execute(
                "UPDATE splits SET amount = ? WHERE amount = -2", (-top - 1,)
            )
            # Proof that a plain SQL SUM cannot read this book.
            with pytest.raises(sqlite3.OperationalError, match="integer overflow"):
                connection.execute("SELECT SUM(amount) FROM splits").fetchone()
        with Book.open(path) as book:
            assert book.accounts.balance(account.id) == -2
            assert book.accounts.net_worth().net_worth == -2
            assert book.investments.net_worth().net_worth == -2
            summary = book.periods.summary(period.id)
            assert (summary.income, summary.expenses) == (2 * top, 2 * (-top - 1))
            assert summary.uncategorized == 2 * top


class TestRegister:
    def test_running_balance(
        self, book: Book, checking: Account, savings: Account, food: Category
    ) -> None:
        book.accounts.update(checking.id, opening_balance=1000, opening_date=d(1))
        t1 = book.transactions.record_expense(
            d(2), 100, account_id=checking.id, category_id=food.id
        )
        t2 = book.transactions.record_transfer(
            d(3), 300, from_account_id=checking.id, to_account_id=savings.id
        )
        t3 = book.transactions.record_income(d(4), 50, account_id=checking.id)
        book.transactions.record_income(d(4), 999, account_id=savings.id)

        register = book.accounts.register(checking.id)
        assert register.starting_balance == 1000
        assert [(e.transaction.id, e.amount, e.balance) for e in register.entries] == [
            (t1.id, -100, 900),
            (t2.id, -300, 600),
            (t3.id, 50, 650),
        ]
        assert register.ending_balance == 650 == book.accounts.balance(checking.id)

        window = book.accounts.register(checking.id, start=d(3), end=d(3))
        assert window.starting_balance == 900
        assert [e.balance for e in window.entries] == [600]
        assert window.ending_balance == 600

    def test_opening_balance_inside_and_outside_window(
        self, book: Book, checking: Account
    ) -> None:
        book.accounts.update(checking.id, opening_balance=1000, opening_date=d(10))
        book.transactions.record_income(d(10), 5, account_id=checking.id)
        assert book.accounts.register(checking.id, start=d(1)).starting_balance == 1000
        assert book.accounts.register(checking.id, start=d(11)).starting_balance == 1005
        before = book.accounts.register(checking.id, end=d(5))
        assert (before.starting_balance, before.entries) == (0, ())
        assert before.ending_balance == 0
        early = book.accounts.register(checking.id, start=d(1), end=d(5))
        assert early.starting_balance == 0

    def test_multiple_splits_on_same_account_are_summed(
        self, book: Book, checking: Account
    ) -> None:
        book.transactions.create(
            d(1),
            [
                AccountSplit(checking.id, 100, memo="a"),
                AccountSplit(checking.id, 50, memo="b"),
                ExternalSplit(150),
            ],
        )
        (entry,) = book.accounts.register(checking.id).entries
        assert (entry.amount, entry.balance) == (150, 150)

    def test_invalid_range(self, book: Book, checking: Account) -> None:
        with pytest.raises(ValidationError, match="on or before"):
            book.accounts.register(checking.id, start=d(2), end=d(1))


class TestTrends:
    def test_average_of_complete_months(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        book.accounts.update(checking.id, opening_balance=10_000)
        book.transactions.record_income(d(20, 1), 900, account_id=checking.id)
        book.transactions.record_expense(d(5, 3), 200, account_id=checking.id)
        # The current month and the future are not averaged.
        book.transactions.record_income(d(1, 4), 5000, account_id=checking.id)
        book.transactions.record_income(d(1, 6), 5000, account_id=checking.id)
        book.transactions.record_income(d(1, 4), 100, account_id=savings.id)
        checking_trend, savings_trend = book.accounts.trends(today=d(15, 4))
        assert checking_trend.account == book.accounts.get(checking.id)
        assert (checking_trend.balance, checking_trend.months) == (20_700, 3)
        assert checking_trend.average_flow == round(700 / 3)
        assert checking_trend.low_point is None
        assert (savings_trend.months, savings_trend.average_flow) == (0, None)

    def test_average_of_the_last_three_complete_months(
        self, book: Book, checking: Account
    ) -> None:
        book.transactions.record_income(d(10, 1), 9000, account_id=checking.id)
        book.transactions.record_income(d(1, 3), 300, account_id=checking.id)
        book.transactions.record_expense(d(31, 5), 100, account_id=checking.id)
        (trend,) = book.accounts.trends(today=d(15, 6))
        assert (trend.months, trend.average_flow) == (3, round(200 / 3))

    def test_low_point_of_the_current_debt(self, book: Book, card: Account) -> None:
        book.accounts.update(card.id, opening_balance=-100)
        for day, amount in ((1, -900), (2, 1500), (3, -400), (4, -800), (5, 200)):
            if amount < 0:
                book.transactions.record_expense(d(day), -amount, account_id=card.id)
            else:
                book.transactions.record_income(d(day), amount, account_id=card.id)
        (trend,) = book.accounts.trends(today=d(1, 3))
        assert (trend.balance, trend.low_point) == (-500, -700)
        book.transactions.record_income(d(6), 500, account_id=card.id)
        (settled,) = book.accounts.trends(today=d(1, 3))
        assert (settled.balance, settled.low_point) == (0, None)

    def test_opening_debt_is_the_low_point(self, book: Book) -> None:
        loan = book.accounts.create("Loan", AccountType.LOAN, opening_balance=-5000)
        (trend,) = book.accounts.trends()
        assert (trend.account.id, trend.low_point, trend.months) == (loan.id, -5000, 0)

    def test_closed_accounts(self, book: Book, checking: Account) -> None:
        book.accounts.close(checking.id, on=d(1))
        assert book.accounts.trends() == []
        assert len(book.accounts.trends(include_closed=True)) == 1


def test_unset_is_a_readable_sentinel() -> None:
    assert repr(UNSET) == "UNSET"
