from __future__ import annotations

from decimal import Decimal

import pytest

from picciuli import ValidationError
from picciuli.money import format_amount, from_decimal, parse_amount, to_decimal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0),
        ("12", 1200),
        ("12.3", 1230),
        ("-12.34", -1234),
        ("+1,234.56", 123456),
        ("  7.5 ", 750),
        (".5", 50),
        ("5.", 500),
    ],
)
def test_parse_amount(text: str, expected: int) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize(
    "text", ["", "-", "abc", "1.2.3", "1.234", "--1", "1-", ".", "NaN", "1e3", "١٢"]
)
def test_parse_amount_rejects_invalid_text(text: str) -> None:
    with pytest.raises(ValidationError):
        parse_amount(text)


def test_parse_amount_with_custom_separators_and_digits() -> None:
    assert parse_amount("1.234,5", decimal_separator=",", group_separator=".") == 123450
    assert parse_amount("1234", digits=0) == 1234
    assert parse_amount("1.001", digits=3) == 1001
    with pytest.raises(ValidationError):
        parse_amount("1,000", group_separator=None)
    with pytest.raises(ValidationError):
        parse_amount("1", decimal_separator=",", group_separator=",")
    with pytest.raises(ValidationError):
        parse_amount(12)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("amount", "kwargs", "expected"),
    [
        (0, {}, "0.00"),
        (5, {}, "0.05"),
        (-123456789, {}, "-1,234,567.89"),
        (123450, {"currency": "€"}, "€1,234.50"),
        (-123450, {"currency": "EUR"}, "-EUR 1,234.50"),
        (100, {"plus_sign": True}, "+1.00"),
        (123450, {"decimal_separator": ",", "group_separator": "."}, "1.234,50"),
        (123450, {"group_separator": None}, "1234.50"),
        (1234, {"digits": 0}, "1,234"),
    ],
)
def test_format_amount(amount: int, kwargs: dict[str, object], expected: str) -> None:
    assert format_amount(amount, **kwargs) == expected  # type: ignore[arg-type]


def test_decimal_round_trip() -> None:
    assert to_decimal(1234) == Decimal("12.34")
    assert from_decimal(Decimal("12.34")) == 1234
    assert from_decimal(to_decimal(-987654, digits=3), digits=3) == -987654


def test_decimal_conversion_errors() -> None:
    with pytest.raises(ValidationError):
        from_decimal(Decimal("0.001"))
    with pytest.raises(ValidationError):
        from_decimal(Decimal("Infinity"))
    with pytest.raises(ValidationError):
        to_decimal(True)
    with pytest.raises(ValidationError):
        to_decimal(1, digits=7)
    with pytest.raises(ValidationError):
        to_decimal(1, digits=1.5)  # type: ignore[arg-type]
