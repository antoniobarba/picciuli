"""Base classes of the API bodies."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, PlainSerializer

__all__ = ["DecimalStr", "InputModel", "OutputModel", "PatchModel"]

DecimalStr = Annotated[
    Decimal,
    PlainSerializer(
        lambda value: format(value, "f"), return_type=str, when_used="json"
    ),
]
"""A decimal written as a plain string, never in exponent notation."""


class OutputModel(BaseModel):
    """A response body, built from a library object with `model_validate`."""

    model_config = ConfigDict(from_attributes=True)


class InputModel(BaseModel):
    """A request body. Unknown fields are rejected to catch typos early."""

    model_config = ConfigDict(extra="forbid")


class PatchModel(InputModel):
    """A partial update: only the fields present in the request are changed."""

    def changes(self) -> dict[str, Any]:
        """Return the fields explicitly set by the client."""
        return {name: getattr(self, name) for name in self.model_fields_set}
