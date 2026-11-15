"""Bodies of the category endpoints."""

from __future__ import annotations

from pydantic import Field

from .base import InputModel, OutputModel, PatchModel

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

    name: str = Field(examples=["Groceries"])
    parent_id: int | None = None
    symbol: str | None = None


class CategoryUpdate(PatchModel):
    """Changes to a category. `parent_id: null` makes it a top-level category."""

    name: str | None = None
    symbol: str | None = None
    parent_id: int | None = None
    position: int | None = Field(default=None, ge=1)
