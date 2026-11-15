"""Bodies of the category endpoints."""

from __future__ import annotations

from pydantic import Field

from .base import (
    CategorySymbol,
    Id,
    InputModel,
    Name,
    OutputModel,
    PatchModel,
    Position,
)

__all__ = ["CategoryCreate", "CategoryOut", "CategoryUpdate"]


class CategoryOut(OutputModel):
    """A label for external cash flows, in a two-level tree."""

    id: int
    name: str
    symbol: str
    parent_id: int | None
    position: int


class CategoryCreate(InputModel):
    """A new category."""

    name: Name = Field(examples=["Groceries"])
    parent_id: Id | None = None
    symbol: CategorySymbol | None = None


class CategoryUpdate(PatchModel):
    """Changes to a category. `parent_id: null` makes it a top-level category."""

    _not_null = frozenset({"name", "position"})

    name: Name | None = None
    symbol: CategorySymbol | None = None
    parent_id: Id | None = None
    position: Position | None = None
