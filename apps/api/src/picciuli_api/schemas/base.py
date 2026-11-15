"""Base classes and constrained types of the API bodies and parameters."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Annotated, Any, ClassVar

from fastapi import Path, Query
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationInfo,
    WithJsonSchema,
    field_validator,
)

from picciuli.limits import (
    DECIMAL_PLACES,
    MAX_AMOUNT,
    MAX_CATEGORY_SYMBOL_LENGTH,
    MAX_ID,
    MAX_MEMO_LENGTH,
    MAX_NAME_LENGTH,
    MAX_SYMBOL_LENGTH,
    MAX_TEXT_LENGTH,
)

__all__ = [
    "DECIMAL_LIMIT",
    "MAX_LIST_LENGTH",
    "Amount",
    "CategorySymbol",
    "CurrencyCode",
    "Date",
    "DecimalStr",
    "Id",
    "InputModel",
    "Memo",
    "Name",
    "NonNegativeAmount",
    "OutputModel",
    "PatchModel",
    "PathCurrency",
    "PathDate",
    "PathId",
    "Position",
    "PositiveAmount",
    "PositiveDecimal",
    "QueryDate",
    "QueryId",
    "QueryPositiveDecimal",
    "SignedDecimal",
    "Symbol",
    "Text",
]

MAX_LIST_LENGTH = 1000
"""Longest list of identifiers or codes accepted in a body."""

DecimalStr = Annotated[
    Decimal,
    PlainSerializer(
        lambda value: format(value, "f"), return_type=str, when_used="json"
    ),
]
"""A decimal written as a plain string, never in exponent notation."""

Amount = Annotated[
    int,
    Field(
        ge=-MAX_AMOUNT,
        le=MAX_AMOUNT,
        description="Amount in minor units, at most 10^15 in absolute value.",
    ),
]
PositiveAmount = Annotated[int, Field(gt=0, le=MAX_AMOUNT)]
NonNegativeAmount = Annotated[int, Field(ge=0, le=MAX_AMOUNT)]

Id = Annotated[int, Field(ge=1, le=MAX_ID)]
"""Identifier of a stored entity."""
Position = Annotated[int, Field(ge=1, le=MAX_ID)]

DECIMAL_LIMIT = Decimal(10**10)
"""Quantities, prices and rates sent to the API must be below this value.

It is lower than the library limit (`picciuli.limits.MAX_DECIMAL`) so that the
documented bounds are exact in JSON.
"""
_DECIMAL_TEXT = rf"[0-9]{{1,10}}(\.[0-9]{{1,{DECIMAL_PLACES}}})?"


def _decimal_text(pattern: str) -> Any:
    regex = re.compile(pattern)

    def check(value: object) -> object:
        if isinstance(value, str) and not regex.fullmatch(value):
            raise ValueError(
                f"expected a decimal number with at most {DECIMAL_PLACES} "
                "decimal places, such as '12.5'"
            )
        return value

    return BeforeValidator(check)


def _decimal_schema(pattern: str, minimum: dict[str, int]) -> WithJsonSchema:
    return WithJsonSchema(
        {
            "anyOf": [
                {"type": "string", "pattern": f"^{pattern}$"},
                {
                    "type": "number",
                    **minimum,
                    "exclusiveMaximum": int(DECIMAL_LIMIT),
                    "multipleOf": float(Decimal(1).scaleb(-DECIMAL_PLACES)),
                },
            ]
        }
    )


_POSITIVE_TEXT = rf"(?=[0-9.]*[1-9]){_DECIMAL_TEXT}"
PositiveDecimal = Annotated[
    Decimal,
    Field(gt=0, lt=DECIMAL_LIMIT, decimal_places=DECIMAL_PLACES),
    _decimal_text(_POSITIVE_TEXT),
    _decimal_schema(_POSITIVE_TEXT, {"exclusiveMinimum": 0}),
]
"""A quantity, price or rate: positive, with at most 8 decimal places."""
QueryPositiveDecimal = Annotated[
    Decimal,
    Field(gt=0, lt=DECIMAL_LIMIT, decimal_places=DECIMAL_PLACES),
    _decimal_text(_POSITIVE_TEXT),
    WithJsonSchema({"type": "string", "pattern": f"^{_POSITIVE_TEXT}$"}),
]
"""`PositiveDecimal` in a query string, where every value is text."""
_SIGNED_TEXT = rf"-?{_DECIMAL_TEXT}"
SignedDecimal = Annotated[
    Decimal,
    Field(gt=-DECIMAL_LIMIT, lt=DECIMAL_LIMIT, decimal_places=DECIMAL_PLACES),
    _decimal_text(_SIGNED_TEXT),
    _decimal_schema(_SIGNED_TEXT, {"exclusiveMinimum": -int(DECIMAL_LIMIT)}),
]
"""A share quantity: negative when shares leave the account."""

Name = Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH)]
Text = Annotated[str, Field(max_length=MAX_TEXT_LENGTH)]
"""A description or notes."""
Memo = Annotated[str, Field(max_length=MAX_MEMO_LENGTH)]
Symbol = Annotated[str, Field(max_length=MAX_SYMBOL_LENGTH)]
"""A ticker symbol."""
CategorySymbol = Annotated[
    str, Field(min_length=1, max_length=MAX_CATEGORY_SYMBOL_LENGTH)
]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$", examples=["EUR"])]

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _strict_date(value: object) -> object:
    """Accept only `YYYY-MM-DD` text or a date; pydantic would take numbers."""
    if isinstance(value, str) and _DATE.fullmatch(value):
        return value
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    raise ValueError("expected a date in YYYY-MM-DD format")


Date = Annotated[dt.date, BeforeValidator(_strict_date)]
"""A day in `YYYY-MM-DD` format (numbers such as `0` are rejected)."""

PathId = Annotated[int, Path(ge=1, le=MAX_ID)]
PathDate = Annotated[Date, Path()]
PathCurrency = Annotated[str, Path(pattern=r"^[A-Za-z]{3}$", examples=["USD"])]
QueryId = Annotated[int | None, Query(ge=1, le=MAX_ID)]
QueryDate = Annotated[Date | None, Query()]


class OutputModel(BaseModel):
    """A response body, built from a library object with `model_validate`."""

    model_config = ConfigDict(from_attributes=True)


class InputModel(BaseModel):
    """A request body. Unknown fields are rejected to catch typos early."""

    model_config = ConfigDict(extra="forbid")


def _not_null_schema(schema: dict[str, Any], cls: type[BaseModel]) -> None:
    """Document the fields of `cls._not_null` as optional but not nullable."""
    properties = schema.get("properties", {})
    for name in getattr(cls, "_not_null", ()):
        field = properties[name]
        options = [o for o in field.pop("anyOf", []) if o.get("type") != "null"]
        field.update(options[0] if len(options) == 1 else {"anyOf": options})
        field.pop("default", None)


class PatchModel(InputModel):
    """A partial update: only the fields present in the request are changed.

    Fields named in `_not_null` cannot be cleared: they may be omitted, but
    not set to `null`.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra=_not_null_schema)

    _not_null: ClassVar[frozenset[str]] = frozenset()

    @field_validator("*", mode="before")
    @classmethod
    def _reject_null(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None and info.field_name in cls._not_null:
            raise ValueError("cannot be null; omit the field to keep its value")
        return value

    def changes(self) -> dict[str, Any]:
        """Return the fields explicitly set by the client."""
        return {name: getattr(self, name) for name in self.model_fields_set}
