"""Text formatting shared by every screen: amounts, dates and labels."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from picciuli import (
    Account,
    AccountType,
    Category,
    CostMethod,
    Period,
    SecurityKind,
    Settings,
    Transaction,
    TransactionKind,
)
from picciuli.money import format_amount, parse_amount, to_decimal

ACCOUNT_TYPE_LABELS: Mapping[AccountType, str] = {
    AccountType.CHECKING: "Checking",
    AccountType.SAVINGS: "Savings",
    AccountType.CASH: "Cash",
    AccountType.INVESTMENT: "Investment",
    AccountType.OTHER_ASSET: "Other asset",
    AccountType.CREDIT_CARD: "Credit card",
    AccountType.LOAN: "Loan",
    AccountType.MORTGAGE: "Mortgage",
    AccountType.OTHER_LIABILITY: "Other liability",
}

_COMPACT_UNITS = (
    (Decimal(1), ""),
    (Decimal(1_000), "k"),
    (Decimal(1_000_000), "M"),
    (Decimal(1_000_000_000), "G"),
)


def _round(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MoneyFormat:
    """How amounts are shown and typed, derived from the book settings."""

    currency: str = "$"
    digits: int = 2

    @classmethod
    def from_settings(cls, settings: Settings) -> MoneyFormat:
        """Build the format of a book from its settings."""
        return cls(settings.currency, settings.minor_digits)

    def amount(self, value: int, *, currency: bool = True, plus: bool = False) -> str:
        """Return `value` as text, for example `-$1,234.50`."""
        return format_amount(
            value,
            currency=self.currency if currency else None,
            digits=self.digits,
            plus_sign=plus,
        )

    def plain(self, value: int) -> str:
        """Return `value` as editable text without currency or grouping."""
        return format_amount(value, digits=self.digits, group_separator=None)

    def parse(self, text: str) -> int:
        """Parse typed text into minor units (raises `ValidationError`)."""
        return parse_amount(text, digits=self.digits)

    def compact(self, value: int) -> str:
        """Return a signed amount in at most six characters, e.g. `-45` or `+2.1k`.

        Amounts are rounded to whole currency units, except below ten where one
        decimal is kept.
        """
        sign = "-" if value < 0 else "+"
        major = abs(to_decimal(value, digits=self.digits))
        rounded, suffix = major, ""
        for unit, suffix in _COMPACT_UNITS:
            scaled = major / unit
            places = 1 if scaled < 10 and (suffix or self.digits) else 0
            rounded = _round(scaled, places)
            # Move to the next unit when rounding reaches 1000 (999.96 -> 1k).
            if rounded < 1000 or suffix == _COMPACT_UNITS[-1][1]:
                break
        text = f"{rounded:f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return f"{sign}{text}{suffix}"


def short_date(day: dt.date) -> str:
    """Return a day as `03 Feb 2025`."""
    return day.strftime("%d %b %Y")


def long_date(day: dt.date) -> str:
    """Return a day as `Monday 03 February 2025`."""
    return day.strftime("%A %d %B %Y")


def period_range(period: Period) -> str:
    """Return the days of a period, for example `01 Feb 2025 – open`."""
    end = short_date(period.end) if period.end is not None else "open"
    return f"{short_date(period.start)} – {end}"


def category_label(category_id: int | None, categories: Mapping[int, Category]) -> str:
    """Return `Parent › Child`, the category name, or `Uncategorized`."""
    if category_id is None:
        return "Uncategorized"
    category = categories.get(category_id)
    if category is None:
        return f"#{category_id}"
    if category.parent_id is not None and category.parent_id in categories:
        return f"{categories[category.parent_id].name} › {category.name}"
    return category.name


def category_tree_label(category: Category) -> str:
    """Return the category name indented when it is a subcategory."""
    return f"  └ {category.name}" if category.parent_id is not None else category.name


def account_name(account_id: int, accounts: Mapping[int, Account]) -> str:
    """Return the name of an account, or `#id` if it is unknown."""
    account = accounts.get(account_id)
    return account.name if account is not None else f"#{account_id}"


def transaction_accounts(
    transaction: Transaction, accounts: Mapping[int, Account]
) -> str:
    """Return the accounts touched by a transaction, e.g. `Checking → Savings`."""
    outgoing = [s for s in transaction.account_splits if s.amount < 0]
    incoming = [s for s in transaction.account_splits if s.amount > 0]
    if transaction.kind is TransactionKind.TRANSFER and outgoing and incoming:
        left = ", ".join(account_name(s.account_id, accounts) for s in outgoing)
        right = ", ".join(account_name(s.account_id, accounts) for s in incoming)
        return f"{left} → {right}"
    return ", ".join(
        account_name(s.account_id, accounts) for s in transaction.account_splits
    )


def transaction_category(
    transaction: Transaction, categories: Mapping[int, Category]
) -> str:
    """Return the category column of a transaction."""
    external = transaction.external_splits
    if not external:
        return "Transfer"
    labels = {category_label(s.category_id, categories) for s in external}
    if len(labels) == 1:
        return labels.pop()
    return f"Split ({len(external)})"


def transaction_title(transaction: Transaction) -> str:
    """Return the description of a transaction, or a placeholder."""
    return transaction.description or f"({transaction.kind.value})"


def account_change(transaction: Transaction, account_id: int) -> int:
    """Return how much a transaction changes one account."""
    return sum(
        s.amount for s in transaction.account_splits if s.account_id == account_id
    )


def progress_bar(fraction: float, width: int = 10) -> str:
    """Return a bar such as `██████░░░░` for a fraction between 0 and 1."""
    clamped = min(max(fraction, 0.0), 1.0)
    filled = round(clamped * width)
    return "█" * filled + "░" * (width - filled)


SECURITY_KIND_LABELS: Mapping[SecurityKind, str] = {
    SecurityKind.STOCK: "Stock",
    SecurityKind.ETF: "ETF",
    SecurityKind.FUND: "Fund",
    SecurityKind.BOND: "Bond",
    SecurityKind.CRYPTO: "Crypto",
    SecurityKind.OTHER: "Other",
}

COST_METHOD_LABELS: Mapping[CostMethod, str] = {
    CostMethod.AVERAGE: "Weighted average cost",
    CostMethod.FIFO: "First in, first out (FIFO)",
}


def quantity_text(value: Decimal) -> str:
    """Return a number of shares without useless zeros, e.g. `1,234.5`."""
    text = f"{value:,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def price_text(value: Decimal, currency: str) -> str:
    """Return a price with at least two decimals, e.g. `169.86 EUR`."""
    exponent = value.normalize().as_tuple().exponent
    places = max(2, -exponent) if isinstance(exponent, int) else 2
    return f"{value:,.{places}f} {currency}"


def percent_text(part: int, whole: int) -> str:
    """Return `part / whole` as a signed percentage, or an empty string."""
    if not whole:
        return ""
    return f"{part / abs(whole):+.1%}"
