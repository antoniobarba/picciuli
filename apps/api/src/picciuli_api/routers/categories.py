"""Category endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from picciuli import UNSET, Unset, ValidationError
from picciuli_api.deps import BookDep
from picciuli_api.schemas.categories import CategoryCreate, CategoryOut, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("")
def list_categories(
    book: BookDep,
    top_level: Annotated[
        bool, Query(description="Only return the top-level categories.")
    ] = False,
) -> list[CategoryOut]:
    """List the categories in display order (parents before their children)."""
    categories = book.categories.children(None) if top_level else book.categories.list()
    return [CategoryOut.model_validate(c) for c in categories]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(book: BookDep, body: CategoryCreate) -> CategoryOut:
    """Create a category, optionally under a top-level parent."""
    category = book.categories.create(
        body.name, parent_id=body.parent_id, symbol=body.symbol
    )
    return CategoryOut.model_validate(category)


@router.get("/{category_id}")
def get_category(book: BookDep, category_id: int) -> CategoryOut:
    """Get one category."""
    return CategoryOut.model_validate(book.categories.get(category_id))


@router.get("/{category_id}/children")
def list_children(book: BookDep, category_id: int) -> list[CategoryOut]:
    """List the subcategories of a category."""
    book.categories.get(category_id)
    return [
        CategoryOut.model_validate(c) for c in book.categories.children(category_id)
    ]


@router.patch("/{category_id}")
def update_category(
    book: BookDep, category_id: int, body: CategoryUpdate
) -> CategoryOut:
    """Rename, move or re-parent a category."""
    category = book.categories.update(category_id, **body.changes())
    return CategoryOut.model_validate(category)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    book: BookDep,
    category_id: int,
    reassign_to: Annotated[
        int | None, Query(description="Move the category's splits to this category.")
    ] = None,
    uncategorize: Annotated[
        bool, Query(description="Leave the category's splits uncategorized.")
    ] = False,
) -> None:
    """Delete a category.

    A category in use can only be deleted with `reassign_to` or `uncategorize`.
    Its budgets are deleted too.
    """
    if uncategorize and reassign_to is not None:
        raise ValidationError("use either reassign_to or uncategorize, not both")
    target: int | None | Unset = UNSET
    if uncategorize:
        target = None
    elif reassign_to is not None:
        target = reassign_to
    book.categories.delete(category_id, reassign_to=target)
