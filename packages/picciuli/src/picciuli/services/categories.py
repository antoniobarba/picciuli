"""Categories: a two-level, ordered tree used to classify external flows."""

from __future__ import annotations

import builtins

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._db.queries import get_row, ordered_categories, to_category
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import BudgetRow, CategoryRow, SplitRow
from picciuli.errors import ConflictError, ValidationError
from picciuli.limits import MAX_CATEGORY_SYMBOL_LENGTH
from picciuli.model import UNSET, Category, Unset

__all__ = ["CategoryService"]


def _symbol(value: object, name: str) -> str:
    if value is None:
        initials = "".join(part[0] for part in name.split())[:4]
        value = (initials if len(initials) > 1 else name[:4]).upper()
    if not isinstance(value, str):
        raise ValidationError("category symbol must be a string")
    symbol = value.strip()
    if not symbol:
        raise ValidationError("category symbol cannot be empty")
    if len(symbol) > MAX_CATEGORY_SYMBOL_LENGTH:
        raise ValidationError(
            f"category symbol cannot exceed {MAX_CATEGORY_SYMBOL_LENGTH} characters"
        )
    if not symbol.isprintable():
        raise ValidationError("category symbol must contain only printable characters")
    return symbol


def _ensure_unique_name(
    session: Session, name: str, exclude: int | None = None
) -> None:
    folded = name.casefold()
    for row_id, existing in session.execute(select(CategoryRow.id, CategoryRow.name)):
        if row_id != exclude and existing.casefold() == folded:
            raise ConflictError(f"a category named {existing!r} already exists")


def _siblings(session: Session, parent_id: int | None) -> list[CategoryRow]:
    condition = (
        CategoryRow.parent_id.is_(None)
        if parent_id is None
        else CategoryRow.parent_id == parent_id
    )
    return list(
        session.scalars(
            select(CategoryRow)
            .where(condition)
            .order_by(CategoryRow.position, CategoryRow.id)
        )
    )


def _renumber(rows: builtins.list[CategoryRow]) -> None:
    for index, row in enumerate(rows, start=1):
        row.position = index


def _valid_parent(session: Session, parent_id: object, child_id: int | None) -> int:
    parent_id = v.identifier(parent_id, "parent id")
    if parent_id == child_id:
        raise ValidationError("a category cannot be its own parent")
    parent = get_row(session, CategoryRow, parent_id, "parent category")
    if parent.parent_id is not None:
        raise ValidationError("subcategories cannot have subcategories")
    return parent.id


class CategoryService:
    """Manage categories.

    Obtain it as [`Book.categories`][picciuli.Book.categories].

    Categories form a two-level tree: top-level categories may contain
    subcategories, which cannot have children of their own. Each category has a
    1-based position among its siblings.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(
        self,
        name: str,
        *,
        parent_id: int | None = None,
        symbol: str | None = None,
    ) -> Category:
        """Create a category at the end of its sibling group.

        Args:
            name: Unique name (case-insensitive).
            parent_id: Top-level category to nest under, or `None`.
            symbol: Short label of at most 12 characters; by default the
                upper-cased initials of the name (or its first four letters).

        Raises:
            ValidationError: If an argument is invalid or the parent is itself a
                subcategory.
            NotFoundError: If the parent does not exist.
            ConflictError: If the name is already used.
        """
        name = v.name(name, "category name")
        symbol = _symbol(symbol, name)
        with self._uow.session() as session:
            _ensure_unique_name(session, name)
            parent = (
                None if parent_id is None else _valid_parent(session, parent_id, None)
            )
            last = session.scalar(
                select(func.max(CategoryRow.position)).where(
                    CategoryRow.parent_id.is_(None)
                    if parent is None
                    else CategoryRow.parent_id == parent
                )
            )
            row = CategoryRow(
                name=name, symbol=symbol, parent_id=parent, position=(last or 0) + 1
            )
            session.add(row)
            session.flush()
            return to_category(row)

    def get(self, category_id: int) -> Category:
        """Return a category.

        Raises:
            NotFoundError: If the category does not exist.
        """
        with self._uow.session() as session:
            return to_category(get_row(session, CategoryRow, category_id, "category"))

    def list(self) -> builtins.list[Category]:
        """Return all categories in display order.

        Each top-level category is immediately followed by its subcategories.
        """
        with self._uow.session() as session:
            return [to_category(row) for row in ordered_categories(session)]

    def children(self, parent_id: int | None) -> builtins.list[Category]:
        """Return the direct children of a category, or the top-level categories.

        Args:
            parent_id: A top-level category, or `None` for the top level.

        Raises:
            NotFoundError: If the parent does not exist.
        """
        with self._uow.session() as session:
            if parent_id is not None:
                get_row(session, CategoryRow, parent_id, "category")
            return [to_category(row) for row in _siblings(session, parent_id)]

    def update(
        self,
        category_id: int,
        *,
        name: str | Unset = UNSET,
        symbol: str | None | Unset = UNSET,
        parent_id: int | None | Unset = UNSET,
        position: int | Unset = UNSET,
    ) -> Category:
        """Rename, re-symbol, move or reorder a category.

        Arguments left `UNSET` are not modified.

        Args:
            category_id: Category to change.
            name: New unique name.
            symbol: New symbol; `None` derives it from the (new) name.
            parent_id: New parent, or `None` to make it top-level. A category
                with subcategories cannot become a subcategory.
            position: New 1-based position in the (new) sibling group. When the
                parent changes and no position is given, it goes last.

        Raises:
            NotFoundError: If the category or the parent does not exist.
            ValidationError: If an argument is invalid or the tree would get more
                than two levels.
            ConflictError: If the name is already used.
        """
        with self._uow.session() as session:
            row = get_row(session, CategoryRow, category_id, "category")
            if not isinstance(name, Unset):
                new_name = v.name(name, "category name")
                _ensure_unique_name(session, new_name, exclude=row.id)
                row.name = new_name
            if not isinstance(symbol, Unset):
                row.symbol = _symbol(symbol, row.name)
            new_parent = row.parent_id
            if not isinstance(parent_id, Unset) and parent_id is not None:
                new_parent = _valid_parent(session, parent_id, row.id)
                if _siblings(session, row.id):
                    raise ValidationError(
                        "a category with subcategories cannot become a subcategory"
                    )
            elif parent_id is None:
                new_parent = None
            old_group = _siblings(session, row.parent_id)
            if new_parent == row.parent_id:
                target = [r for r in old_group if r.id != row.id]
                index = next(i for i, r in enumerate(old_group) if r.id == row.id)
            else:
                _renumber([r for r in old_group if r.id != row.id])
                target = _siblings(session, new_parent)
                index = len(target)
            if not isinstance(position, Unset):
                index = v.position(position, len(target) + 1) - 1
            target.insert(index, row)
            row.parent_id = new_parent
            _renumber(target)
            session.flush()
            return to_category(row)

    def delete(
        self, category_id: int, *, reassign_to: int | None | Unset = UNSET
    ) -> None:
        """Delete a category and its budgets.

        Args:
            category_id: Category to delete. It must not have subcategories.
            reassign_to: Where to move the external splits that use the
                category: another category, or `None` to leave them
                uncategorized. Required when the category is in use.

        Raises:
            NotFoundError: If the category or the reassignment target does not
                exist.
            ValidationError: If the category would be reassigned to itself.
            ConflictError: If the category has subcategories, or is used and no
                `reassign_to` was given.
        """
        with self._uow.session() as session:
            row = get_row(session, CategoryRow, category_id, "category")
            if _siblings(session, row.id):
                raise ConflictError("delete or move the subcategories first")
            used = session.scalar(
                select(func.count())
                .select_from(SplitRow)
                .where(SplitRow.category_id == row.id)
            )
            if used and isinstance(reassign_to, Unset):
                raise ConflictError(
                    f"category {row.name!r} is used by {used} split(s); "
                    "pass reassign_to to move them"
                )
            target: int | None = None
            if not isinstance(reassign_to, Unset) and reassign_to is not None:
                target = v.identifier(reassign_to, "reassign_to")
                if target == row.id:
                    raise ValidationError("cannot reassign a category to itself")
                get_row(session, CategoryRow, target, "category")
            if used:
                session.execute(
                    update(SplitRow)
                    .where(SplitRow.category_id == row.id)
                    .values(category_id=target)
                )
            session.execute(delete(BudgetRow).where(BudgetRow.category_id == row.id))
            parent_id = row.parent_id
            session.delete(row)
            session.flush()
            _renumber(_siblings(session, parent_id))
