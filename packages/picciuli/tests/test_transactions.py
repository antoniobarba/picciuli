from __future__ import annotations

import datetime as dt

import pytest

from picciuli import (
    Account,
    AccountSplit,
    Book,
    Category,
    ConflictError,
    ExternalSplit,
    NotFoundError,
    Split,
    Transaction,
    TransactionKind,
    ValidationError,
)
from picciuli.limits import MAX_AMOUNT

from .conftest import d


class TestCreate:
    def test_expense(self, book: Book, checking: Account, food: Category) -> None:
        tx = book.transactions.record_expense(
            d(3),
            4250,
            account_id=checking.id,
            category_id=food.id,
            description=" Market ",
            notes="",
        )
        assert tx.date == d(3)
        assert (tx.description, tx.notes) == ("Market", None)
        assert tx.splits == (
            AccountSplit(checking.id, -4250),
            ExternalSplit(-4250, food.id),
        )
        assert tx.kind is TransactionKind.EXPENSE
        assert tx.net_amount == -4250
        assert book.transactions.get(tx.id) == tx

    def test_income_and_transfer(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        income = book.transactions.record_income(d(1), 100, account_id=checking.id)
        assert income.kind is TransactionKind.INCOME
        assert income.external_splits == (ExternalSplit(100),)
        transfer = book.transactions.record_transfer(
            d(2), 40, from_account_id=checking.id, to_account_id=savings.id
        )
        assert transfer.kind is TransactionKind.TRANSFER
        assert transfer.net_amount == 0
        assert transfer.account_splits == (
            AccountSplit(checking.id, -40),
            AccountSplit(savings.id, 40),
        )

    def test_loan_payment_and_mixed(self, book: Book, checking: Account) -> None:
        loan = book.accounts.create("Loan", "loan", opening_balance=-10_000)
        payment = book.transactions.create(
            d(1),
            [
                AccountSplit(checking.id, -500),
                AccountSplit(loan.id, 400, memo="principal"),
                ExternalSplit(-100, memo="interest"),
            ],
        )
        assert payment.kind is TransactionKind.EXPENSE
        assert book.accounts.balance(loan.id) == -9_600
        mixed = book.transactions.create(
            d(2),
            [AccountSplit(checking.id, -30), ExternalSplit(-50), ExternalSplit(20)],
        )
        assert mixed.kind is TransactionKind.MIXED

    @pytest.mark.parametrize(
        ("splits", "message"),
        [
            ([], "at least one split"),
            ("splits", "sequence"),
            ([ExternalSplit(-5)], "at least one account split"),
            (["x"], "AccountSplit or an ExternalSplit"),
            ([AccountSplit(1, 0)], "cannot be zero"),
            ([AccountSplit(1, 1.5)], "integer"),  # type: ignore[arg-type]
            ([AccountSplit(1, -5), ExternalSplit(-4)], "unbalanced"),
            ([AccountSplit(1, -5)], "unbalanced"),
            ([AccountSplit(1, 5, memo=3)], "memo"),  # type: ignore[arg-type]
            ([AccountSplit("1", 5)], "account id"),  # type: ignore[arg-type]
            ([AccountSplit(1, 5), ExternalSplit(5, "x")], "category id"),  # type: ignore[arg-type]
            ([AccountSplit(1, MAX_AMOUNT + 1)], "cannot exceed 10+ in absolute"),
            ([AccountSplit(1, -(2**63))], "cannot exceed"),
            ([AccountSplit(1, 5, memo="m" * 501)], "memo cannot exceed 500"),
            ([AccountSplit(1, 1)] * 101, "more than 100 splits"),
        ],
    )
    def test_invalid_splits(
        self, book: Book, checking: Account, splits: object, message: str
    ) -> None:
        with pytest.raises(ValidationError, match=message):
            book.transactions.create(d(1), splits)  # type: ignore[arg-type]

    def test_references_must_exist(self, book: Book, checking: Account) -> None:
        with pytest.raises(NotFoundError, match="account 99"):
            book.transactions.create(d(1), [AccountSplit(99, 5), ExternalSplit(5)])
        with pytest.raises(NotFoundError, match="category 99"):
            book.transactions.create(
                d(1), [AccountSplit(checking.id, 5), ExternalSplit(5, 99)]
            )

    def test_date_rules(self, book: Book, checking: Account) -> None:
        book.accounts.update(checking.id, opening_date=d(5))
        with pytest.raises(ValidationError, match="opens on"):
            book.transactions.record_income(d(4), 5, account_id=checking.id)
        with pytest.raises(ValidationError, match="without time"):
            book.transactions.record_income(
                dt.datetime(2025, 1, 6), 5, account_id=checking.id
            )

    def test_helper_validation(self, book: Book, checking: Account) -> None:
        with pytest.raises(ValidationError, match="greater than zero"):
            book.transactions.record_expense(d(1), -5, account_id=checking.id)
        with pytest.raises(ValidationError, match="greater than zero"):
            book.transactions.record_income(d(1), 0, account_id=checking.id)
        with pytest.raises(ValidationError, match="same account"):
            book.transactions.record_transfer(
                d(1), 5, from_account_id=checking.id, to_account_id=checking.id
            )

    def test_amount_and_text_limits(self, book: Book, checking: Account) -> None:
        book.transactions.record_income(
            d(1), MAX_AMOUNT, account_id=checking.id, notes="n" * 2000
        )
        with pytest.raises(ValidationError, match="amount cannot exceed"):
            book.transactions.record_income(
                d(1), MAX_AMOUNT + 1, account_id=checking.id
            )
        with pytest.raises(ValidationError, match="amount cannot exceed"):
            book.transactions.record_expense(d(1), 2**63, account_id=checking.id)
        with pytest.raises(ValidationError, match="notes cannot exceed 2000"):
            book.transactions.record_income(
                d(1), 5, account_id=checking.id, notes="n" * 2001
            )
        with pytest.raises(ValidationError, match="description cannot exceed"):
            book.transactions.record_income(
                d(1), 5, account_id=checking.id, description="d" * 2001
            )


class TestUpdateDelete:
    def test_update_fields(
        self, book: Book, checking: Account, savings: Account, food: Category
    ) -> None:
        tx = book.transactions.record_expense(
            d(1), 100, account_id=checking.id, category_id=food.id, description="a"
        )
        new_splits: list[Split] = [
            AccountSplit(savings.id, -60),
            ExternalSplit(-60),
        ]
        updated = book.transactions.update(
            tx.id, date=d(2), splits=new_splits, description=None, notes="n"
        )
        assert updated == Transaction(
            id=tx.id, date=d(2), description=None, notes="n", splits=tuple(new_splits)
        )
        assert book.accounts.balance(checking.id) == 0
        assert book.accounts.balance(savings.id) == -60
        assert book.transactions.update(tx.id, description="b").splits == tuple(
            new_splits
        )

    def test_update_revalidates_existing_splits_against_new_date(
        self, book: Book, checking: Account
    ) -> None:
        book.accounts.update(checking.id, opening_date=d(5))
        tx = book.transactions.record_income(d(5), 1, account_id=checking.id)
        with pytest.raises(ValidationError, match="opens on"):
            book.transactions.update(tx.id, date=d(4))
        assert book.transactions.get(tx.id).date == d(5)

    def test_invalid_update_keeps_transaction(
        self, book: Book, checking: Account
    ) -> None:
        tx = book.transactions.record_income(d(1), 1, account_id=checking.id)
        with pytest.raises(ValidationError):
            book.transactions.update(tx.id, splits=[AccountSplit(checking.id, 5)])
        assert book.transactions.get(tx.id) == tx

    def test_update_to_closed_account_is_refused(
        self, book: Book, checking: Account, savings: Account
    ) -> None:
        tx = book.transactions.record_income(d(1), 1, account_id=checking.id)
        book.accounts.close(savings.id, on=d(1))
        with pytest.raises(ConflictError, match="closed"):
            book.transactions.update(
                tx.id, splits=[AccountSplit(savings.id, 1), ExternalSplit(1)]
            )

    def test_delete(self, book: Book, checking: Account) -> None:
        tx = book.transactions.record_income(d(1), 1, account_id=checking.id)
        book.transactions.delete(tx.id)
        with pytest.raises(NotFoundError):
            book.transactions.get(tx.id)
        with pytest.raises(NotFoundError):
            book.transactions.delete(tx.id)
        assert book.accounts.balance(checking.id) == 0


class TestQueries:
    @pytest.fixture
    def data(
        self, book: Book, checking: Account, savings: Account, food: Category
    ) -> dict[str, Transaction]:
        groceries = book.categories.create("Groceries", parent_id=food.id)
        return {
            "salary": book.transactions.record_income(
                d(1), 1000, account_id=checking.id, description="Salary ACME"
            ),
            "food": book.transactions.record_expense(
                d(2),
                10,
                account_id=checking.id,
                category_id=food.id,
                notes="50% off",
            ),
            "groceries": book.transactions.record_expense(
                d(3), 20, account_id=savings.id, category_id=groceries.id
            ),
            "transfer": book.transactions.record_transfer(
                d(3),
                5,
                from_account_id=checking.id,
                to_account_id=savings.id,
            ),
            "memo": book.transactions.create(
                d(4),
                [AccountSplit(checking.id, -1, memo="Coffee"), ExternalSplit(-1)],
            ),
        }

    @staticmethod
    def ids(items: list[Transaction]) -> list[int]:
        return [t.id for t in items]

    def test_filters(
        self,
        book: Book,
        data: dict[str, Transaction],
        checking: Account,
        savings: Account,
        food: Category,
    ) -> None:
        t = data
        assert self.ids(book.transactions.list()) == [
            t[k].id for k in ("salary", "food", "groceries", "transfer", "memo")
        ]
        assert self.ids(book.transactions.list(start=d(3), end=d(3))) == [
            t["groceries"].id,
            t["transfer"].id,
        ]
        assert self.ids(book.transactions.list(account_id=savings.id)) == [
            t["groceries"].id,
            t["transfer"].id,
        ]
        assert self.ids(book.transactions.list(category_id=food.id)) == [t["food"].id]
        assert self.ids(
            book.transactions.list(category_id=food.id, include_subcategories=True)
        ) == [t["food"].id, t["groceries"].id]
        assert self.ids(book.transactions.list(uncategorized=True)) == [
            t["salary"].id,
            t["memo"].id,
        ]

    def test_text_search_paging_and_order(
        self, book: Book, data: dict[str, Transaction]
    ) -> None:
        t = data
        assert self.ids(book.transactions.list(text="acme")) == [t["salary"].id]
        assert self.ids(book.transactions.list(text="50%")) == [t["food"].id]
        assert self.ids(book.transactions.list(text="coffee")) == [t["memo"].id]
        assert len(book.transactions.list(text="  ")) == 5
        newest = book.transactions.list(newest_first=True, limit=2)
        assert self.ids(newest) == [t["memo"].id, t["transfer"].id]
        page = book.transactions.list(newest_first=True, limit=2, offset=2)
        assert self.ids(page) == [t["groceries"].id, t["food"].id]

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"category_id": 1, "uncategorized": True}, "exclusive"),
            ({"start": d(2), "end": d(1)}, "on or before"),
            ({"limit": -1}, "negative"),
            ({"offset": -1}, "negative"),
            ({"limit": 2**63}, "cannot exceed"),
            ({"offset": 2**63}, "cannot exceed"),
            ({"text": 5}, "string"),
            ({"account_id": "1"}, "account id"),
            ({"category_id": "1"}, "category id"),
            ({"account_id": 2**63}, "account id must be between"),
        ],
    )
    def test_invalid_filters(
        self, book: Book, kwargs: dict[str, object], message: str
    ) -> None:
        with pytest.raises(ValidationError, match=message):
            book.transactions.list(**kwargs)  # type: ignore[arg-type]

    def test_dates_with_transactions(
        self, book: Book, data: dict[str, Transaction], savings: Account
    ) -> None:
        assert book.transactions.dates_with_transactions(d(2), d(31)) == [
            d(2),
            d(3),
            d(4),
        ]
        assert book.transactions.dates_with_transactions(
            d(1), d(31), account_id=savings.id
        ) == [d(3)]
        with pytest.raises(ValidationError):
            book.transactions.dates_with_transactions(d(2), d(1))
