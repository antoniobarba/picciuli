from __future__ import annotations

import pytest

from picciuli import (
    Account,
    Book,
    Category,
    ConflictError,
    ExternalSplit,
    NotFoundError,
    ValidationError,
)

from .conftest import d


def tree(book: Book) -> list[tuple[str, str | None, int]]:
    names = {c.id: c.name for c in book.categories.list()}
    return [
        (c.name, names.get(c.parent_id) if c.parent_id else None, c.position)
        for c in book.categories.list()
    ]


@pytest.fixture
def home(book: Book) -> Category:
    return book.categories.create("Home")


class TestCreate:
    def test_symbols(self, book: Book) -> None:
        assert book.categories.create("Food").symbol == "FOOD"
        assert book.categories.create("Eating out tonight").symbol == "EOT"
        assert book.categories.create("Car", symbol=" 🚗 ").symbol == "🚗"

    @pytest.mark.parametrize(
        ("symbol", "message"),
        [
            ("", "empty"),
            ("x" * 13, "12 characters"),
            ("a\tb", "printable"),
            (1, "string"),
        ],
    )
    def test_invalid_symbol(self, book: Book, symbol: object, message: str) -> None:
        with pytest.raises(ValidationError, match=message):
            book.categories.create("X", symbol=symbol)  # type: ignore[arg-type]

    def test_tree_order(self, book: Book, food: Category, home: Category) -> None:
        book.categories.create("Groceries", parent_id=food.id)
        book.categories.create("Rent", parent_id=home.id)
        book.categories.create("Restaurants", parent_id=food.id)
        assert tree(book) == [
            ("Food", None, 1),
            ("Groceries", "Food", 1),
            ("Restaurants", "Food", 2),
            ("Home", None, 2),
            ("Rent", "Home", 1),
        ]
        assert [c.name for c in book.categories.children(food.id)] == [
            "Groceries",
            "Restaurants",
        ]
        assert [c.name for c in book.categories.children(None)] == ["Food", "Home"]

    def test_rules(self, book: Book, food: Category) -> None:
        sub = book.categories.create("Groceries", parent_id=food.id)
        with pytest.raises(ValidationError, match="subcategories cannot"):
            book.categories.create("Fruit", parent_id=sub.id)
        with pytest.raises(NotFoundError):
            book.categories.create("Fruit", parent_id=99)
        with pytest.raises(ConflictError):
            book.categories.create("FOOD")
        with pytest.raises(NotFoundError):
            book.categories.get(99)
        with pytest.raises(NotFoundError):
            book.categories.children(99)
        assert book.categories.get(sub.id) == sub


class TestUpdate:
    def test_rename_and_symbol(self, book: Book, food: Category) -> None:
        renamed = book.categories.update(food.id, name="Meals")
        assert (renamed.name, renamed.symbol) == ("Meals", "FOOD")
        assert book.categories.update(food.id, symbol=None).symbol == "MEAL"
        assert book.categories.update(food.id, symbol="M").symbol == "M"

    def test_duplicate_name(self, book: Book, food: Category, home: Category) -> None:
        with pytest.raises(ConflictError):
            book.categories.update(home.id, name="food")

    def test_reorder_within_group(self, book: Book) -> None:
        a, _b, c = (book.categories.create(n) for n in "ABC")
        book.categories.update(c.id, position=1)
        assert tree(book) == [("C", None, 1), ("A", None, 2), ("B", None, 3)]
        book.categories.update(c.id, name="Z")
        assert tree(book) == [("Z", None, 1), ("A", None, 2), ("B", None, 3)]
        with pytest.raises(ValidationError, match="between 1 and 3"):
            book.categories.update(a.id, position=4)

    def test_move_between_groups(
        self, book: Book, food: Category, home: Category
    ) -> None:
        groceries = book.categories.create("Groceries", parent_id=food.id)
        book.categories.create("Restaurants", parent_id=food.id)
        book.categories.create("Rent", parent_id=home.id)
        book.categories.update(groceries.id, parent_id=home.id)
        assert tree(book) == [
            ("Food", None, 1),
            ("Restaurants", "Food", 1),
            ("Home", None, 2),
            ("Rent", "Home", 1),
            ("Groceries", "Home", 2),
        ]
        book.categories.update(groceries.id, parent_id=None, position=1)
        assert tree(book) == [
            ("Groceries", None, 1),
            ("Food", None, 2),
            ("Restaurants", "Food", 1),
            ("Home", None, 3),
            ("Rent", "Home", 1),
        ]

    def test_invalid_moves(self, book: Book, food: Category, home: Category) -> None:
        sub = book.categories.create("Groceries", parent_id=food.id)
        with pytest.raises(ValidationError, match="own parent"):
            book.categories.update(home.id, parent_id=home.id)
        with pytest.raises(ValidationError, match="subcategories cannot"):
            book.categories.update(home.id, parent_id=sub.id)
        with pytest.raises(ValidationError, match="cannot become a subcategory"):
            book.categories.update(food.id, parent_id=home.id)
        with pytest.raises(NotFoundError):
            book.categories.update(home.id, parent_id=99)


class TestDelete:
    def test_delete_unused_renumbers(self, book: Book) -> None:
        _a, b, _c = (book.categories.create(n) for n in "ABC")
        book.categories.delete(b.id)
        assert tree(book) == [("A", None, 1), ("C", None, 2)]

    def test_delete_parent_with_children_is_refused(
        self, book: Book, food: Category
    ) -> None:
        book.categories.create("Groceries", parent_id=food.id)
        with pytest.raises(ConflictError, match="subcategories first"):
            book.categories.delete(food.id)

    def test_delete_used_category_requires_reassignment(
        self, book: Book, checking: Account, food: Category, home: Category
    ) -> None:
        tx = book.transactions.record_expense(
            d(1), 100, account_id=checking.id, category_id=food.id
        )
        with pytest.raises(ConflictError, match="reassign_to"):
            book.categories.delete(food.id)
        with pytest.raises(ValidationError, match="itself"):
            book.categories.delete(food.id, reassign_to=food.id)
        with pytest.raises(NotFoundError):
            book.categories.delete(food.id, reassign_to=99)
        book.categories.delete(food.id, reassign_to=home.id)
        assert book.transactions.get(tx.id).external_splits == (
            ExternalSplit(-100, home.id),
        )

    def test_delete_to_uncategorized_and_budgets_go_too(
        self, book: Book, checking: Account, food: Category
    ) -> None:
        period = book.periods.create(d(1))
        book.budgets.create(food.id, period.id, 1000)
        tx = book.transactions.record_expense(
            d(1), 100, account_id=checking.id, category_id=food.id
        )
        book.categories.delete(food.id, reassign_to=None)
        assert book.transactions.get(tx.id).external_splits == (ExternalSplit(-100),)
        assert book.budgets.list() == []
