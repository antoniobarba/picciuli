"""Turn what the user typed into library calls.

Every form of the interface collects plain strings and identifiers in a draft
and hands it to a function of this module, which validates it and calls the
public `picciuli` API. Keeping this logic free of widgets makes it easy to test.
"""

from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Sequence
from dataclasses import dataclass, field

from picciuli import (
    UNSET,
    Account,
    AccountSplit,
    AccountType,
    Book,
    Category,
    ExternalSplit,
    Period,
    Split,
    Transaction,
)
from picciuli_tui.formatting import MoneyFormat


class InputError(ValueError):
    """What the user typed cannot be understood."""


NONE_ID = 0
"""Choice value meaning "no category" or "no parent" (identifiers are positive)."""


def parse_date(text: str, *, today: dt.date) -> dt.date:
    """Parse a typed day.

    Accepted forms: `2025-02-03`, `3/2/2025`, `3/2` (this year), `3` (this
    month), `today`, and offsets such as `+1` or `-7` days from `today`.

    Raises:
        InputError: If the text is not a valid day.
    """
    cleaned = text.strip().lower()
    if not cleaned:
        raise InputError("a date is required")
    if cleaned == "today":
        return today
    try:
        if cleaned[0] in "+-" and cleaned[1:].isdigit():
            return today + dt.timedelta(days=int(cleaned))
        if "-" in cleaned:
            return dt.date.fromisoformat(cleaned)
        parts = [int(part) for part in cleaned.replace(".", "/").split("/")]
        if len(parts) == 1:
            return today.replace(day=parts[0])
        if len(parts) == 2:
            return dt.date(today.year, parts[1], parts[0])
        if len(parts) == 3:
            year = parts[2] + 2000 if parts[2] < 100 else parts[2]
            return dt.date(year, parts[1], parts[0])
    except (ValueError, OverflowError):
        pass
    raise InputError(f"invalid date: {text.strip()!r} (use YYYY-MM-DD or DD/MM/YYYY)")


def optional_date(text: str, *, today: dt.date) -> dt.date | None:
    """Parse a day, or return `None` for empty text."""
    return parse_date(text, today=today) if text.strip() else None


def optional_amount(text: str, money: MoneyFormat) -> int | None:
    """Parse an amount, or return `None` for empty text."""
    return money.parse(text) if text.strip() else None


def positive_amount(text: str, money: MoneyFormat) -> int:
    """Parse an amount that must be greater than zero."""
    if not text.strip():
        raise InputError("an amount is required")
    amount = money.parse(text)
    if amount <= 0:
        raise InputError("enter a positive amount")
    return amount


def optional_text(text: str) -> str | None:
    """Return stripped text, or `None` when it is empty."""
    stripped = text.strip()
    return stripped or None


def required_id(value: int | None, label: str) -> int:
    """Return a chosen identifier, or complain that nothing was chosen."""
    if not value:
        raise InputError(f"choose {label}")
    return value


def default_period_name(start: dt.date) -> str:
    """Return the default name of a period starting on `start`."""
    return start.strftime("%B %Y")


# Transactions


class EntryKind(str, enum.Enum):
    """The shapes the transaction form can edit."""

    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"
    SPLIT = "split"


ENTRY_KIND_LABELS = {
    EntryKind.EXPENSE: "Expense",
    EntryKind.INCOME: "Income",
    EntryKind.TRANSFER: "Transfer",
    EntryKind.SPLIT: "Split",
}


def account_target(account_id: int) -> str:
    """Return the split-line target value of an account."""
    return f"a:{account_id}"


def category_target(category_id: int | None) -> str:
    """Return the split-line target value of a category (or uncategorized)."""
    return f"c:{category_id or NONE_ID}"


@dataclass
class LineDraft:
    """One split line as typed in the split editor.

    Attributes:
        target: `a:<account id>` or `c:<category id>` (`c:0` for uncategorized).
        amount: Signed amount text.
        memo: Optional memo.
    """

    target: str = ""
    amount: str = ""
    memo: str = ""


@dataclass
class TransactionDraft:
    """The content of the transaction form.

    `amount`, `account_id`, `category_id` and `to_account_id` are used by the
    simple kinds; `lines` by the split kind.
    """

    kind: EntryKind = EntryKind.EXPENSE
    date: str = ""
    description: str = ""
    notes: str = ""
    amount: str = ""
    account_id: int | None = None
    category_id: int | None = None
    to_account_id: int | None = None
    lines: list[LineDraft] = field(default_factory=list)


def _line_split(line: LineDraft, money: MoneyFormat) -> Split:
    prefix, _, ident = line.target.partition(":")
    if prefix not in {"a", "c"} or not ident.isdigit():
        raise InputError("choose an account or category for every split line")
    if not line.amount.strip():
        raise InputError("every split line needs an amount")
    amount = money.parse(line.amount)
    if amount == 0:
        raise InputError("split amounts cannot be zero")
    memo = optional_text(line.memo)
    if prefix == "a":
        return AccountSplit(int(ident), amount, memo)
    return ExternalSplit(amount, int(ident) or None, memo)


def line_splits(lines: Sequence[LineDraft], money: MoneyFormat) -> list[Split]:
    """Convert split lines into library splits, ignoring completely empty lines."""
    return [
        _line_split(line, money)
        for line in lines
        if line.target or line.amount.strip() or line.memo.strip()
    ]


def line_totals(lines: Sequence[LineDraft], money: MoneyFormat) -> tuple[int, int]:
    """Return the account and external totals of the lines that can be parsed."""
    accounts = external = 0
    for line in lines:
        try:
            split = _line_split(line, money)
        except (InputError, ValueError):
            continue
        if isinstance(split, AccountSplit):
            accounts += split.amount
        else:
            external += split.amount
    return accounts, external


def simple_splits(draft: TransactionDraft, money: MoneyFormat) -> list[Split]:
    """Return the splits of an expense, income or transfer draft."""
    amount = positive_amount(draft.amount, money)
    account = required_id(draft.account_id, "an account")
    if draft.kind is EntryKind.TRANSFER:
        target = required_id(draft.to_account_id, "the destination account")
        if target == account:
            raise InputError("choose two different accounts")
        return [AccountSplit(account, -amount), AccountSplit(target, amount)]
    signed = -amount if draft.kind is EntryKind.EXPENSE else amount
    return [
        AccountSplit(account, signed),
        ExternalSplit(signed, draft.category_id or None),
    ]


def draft_splits(draft: TransactionDraft, money: MoneyFormat) -> list[Split]:
    """Return the splits described by a draft of any kind."""
    if draft.kind is EntryKind.SPLIT:
        return line_splits(draft.lines, money)
    return simple_splits(draft, money)


SPLIT_EDITOR_LINES = 3
"""Minimum number of lines shown when switching to the split editor."""


def simple_lines(draft: TransactionDraft, money: MoneyFormat) -> list[LineDraft]:
    """Convert a simple draft into split lines, for switching to the split editor.

    Empty lines are added up to `SPLIT_EDITOR_LINES`: a typical split takes money
    from one account and sends it to two places.
    """
    try:
        lines = _lines(simple_splits(draft, money), money)
    except (InputError, ValueError):
        lines = [LineDraft(account_target(draft.account_id or NONE_ID))]
    padding = max(0, SPLIT_EDITOR_LINES - len(lines))
    return lines + [LineDraft() for _ in range(padding)]


def _lines(splits: Sequence[Split], money: MoneyFormat) -> list[LineDraft]:
    return [
        LineDraft(
            account_target(s.account_id)
            if isinstance(s, AccountSplit)
            else category_target(s.category_id),
            money.plain(s.amount),
            s.memo or "",
        )
        for s in splits
    ]


def draft_from_transaction(
    transaction: Transaction, money: MoneyFormat
) -> TransactionDraft:
    """Return the draft that edits an existing transaction.

    Transactions with a simple shape open in the matching simple kind;
    everything else opens in the split editor.
    """
    draft = TransactionDraft(
        date=transaction.date.isoformat(),
        description=transaction.description or "",
        notes=transaction.notes or "",
    )
    accounts = transaction.account_splits
    external = transaction.external_splits
    memos = any(split.memo for split in transaction.splits)
    if not memos and len(accounts) == 1 and len(external) == 1:
        account, flow = accounts[0], external[0]
        draft.kind = EntryKind.EXPENSE if flow.amount < 0 else EntryKind.INCOME
        draft.amount = money.plain(abs(flow.amount))
        draft.account_id = account.account_id
        draft.category_id = flow.category_id or NONE_ID
        return draft
    if (
        not memos
        and not external
        and len(accounts) == 2
        and accounts[0].amount == -accounts[1].amount
    ):
        source, target = sorted(accounts, key=lambda split: split.amount)
        draft.kind = EntryKind.TRANSFER
        draft.amount = money.plain(target.amount)
        draft.account_id = source.account_id
        draft.to_account_id = target.account_id
        return draft
    draft.kind = EntryKind.SPLIT
    draft.lines = _lines(transaction.splits, money)
    return draft


def save_transaction(
    book: Book,
    draft: TransactionDraft,
    money: MoneyFormat,
    *,
    today: dt.date,
    transaction_id: int | None = None,
) -> Transaction:
    """Create or update a transaction from a draft."""
    day = parse_date(draft.date, today=today)
    splits = draft_splits(draft, money)
    description = optional_text(draft.description)
    notes = optional_text(draft.notes)
    if transaction_id is None:
        return book.transactions.create(
            day, splits, description=description, notes=notes
        )
    return book.transactions.update(
        transaction_id,
        date=day,
        splits=splits,
        description=description,
        notes=notes,
    )


# Other entities


@dataclass
class AccountDraft:
    """The content of the account form."""

    name: str = ""
    type: AccountType = AccountType.CHECKING
    opening_balance: str = ""
    opening_date: str = ""
    goal: str = ""
    notes: str = ""

    @classmethod
    def of(cls, account: Account, money: MoneyFormat) -> AccountDraft:
        """Return the draft that edits an existing account."""
        return cls(
            name=account.name,
            type=account.type,
            opening_balance=money.plain(account.opening_balance),
            opening_date=account.opening_date.isoformat()
            if account.opening_date
            else "",
            goal=money.plain(account.goal) if account.goal is not None else "",
            notes=account.notes or "",
        )


def save_account(
    book: Book,
    draft: AccountDraft,
    money: MoneyFormat,
    *,
    today: dt.date,
    account_id: int | None = None,
) -> Account:
    """Create or update an account.

    The opening values of an existing account are only sent when they changed,
    so that other properties of a closed account can still be edited.
    """
    opening_balance = optional_amount(draft.opening_balance, money) or 0
    opening_date = optional_date(draft.opening_date, today=today)
    goal = optional_amount(draft.goal, money)
    notes = optional_text(draft.notes)
    if account_id is None:
        return book.accounts.create(
            draft.name,
            draft.type,
            opening_balance=opening_balance,
            opening_date=opening_date,
            goal=goal,
            notes=notes,
        )
    current = book.accounts.get(account_id)
    return book.accounts.update(
        account_id,
        name=draft.name,
        type=draft.type,
        opening_balance=(
            UNSET if opening_balance == current.opening_balance else opening_balance
        ),
        opening_date=UNSET if opening_date == current.opening_date else opening_date,
        goal=goal,
        notes=notes,
    )


def save_category(
    book: Book,
    *,
    name: str,
    symbol: str,
    parent_id: int | None,
    category_id: int | None = None,
) -> Category:
    """Create or update a category. An empty symbol is derived from the name."""
    parent = parent_id or None
    if category_id is None:
        return book.categories.create(
            name, parent_id=parent, symbol=optional_text(symbol)
        )
    current = book.categories.get(category_id)
    return book.categories.update(
        category_id,
        name=name,
        symbol=optional_text(symbol),
        parent_id=UNSET if parent == current.parent_id else parent,
    )


def move_category(book: Book, category: Category, step: int) -> Category:
    """Move a category up (`step=-1`) or down (`step=1`) among its siblings."""
    siblings = book.categories.children(category.parent_id)
    position = min(max(category.position + step, 1), len(siblings))
    return book.categories.update(category.id, position=position)


def category_in_use(book: Book, category_id: int) -> bool:
    """Return whether any transaction uses a category."""
    return bool(book.transactions.list(category_id=category_id, limit=1))


def save_period(
    book: Book,
    *,
    name: str,
    start: str,
    end: str,
    today: dt.date,
    period_id: int | None = None,
) -> Period:
    """Create or update a period. An empty name uses the month of the start."""
    first = parse_date(start, today=today)
    last = optional_date(end, today=today)
    label = optional_text(name) or default_period_name(first)
    if period_id is None:
        return book.periods.create(first, end=last, name=label)
    return book.periods.update(period_id, name=label, start=first, end=last)


def save_budget(
    book: Book,
    money: MoneyFormat,
    *,
    category_id: int | None,
    period_id: int,
    amount: str,
    budget_id: int | None = None,
) -> None:
    """Create or update a budget."""
    category = required_id(category_id, "a category")
    if not amount.strip():
        raise InputError("an amount is required")
    value = money.parse(amount)
    if budget_id is None:
        book.budgets.create(category, period_id, value)
    else:
        book.budgets.update(budget_id, category_id=category, amount=value)


def save_settings(book: Book, *, currency: str, digits: str) -> MoneyFormat:
    """Change the currency settings and return the new money format."""
    try:
        minor_digits = int(digits.strip())
    except ValueError as exc:
        raise InputError("decimal digits must be a whole number") from exc
    return MoneyFormat.from_settings(
        book.settings.update(currency=currency.strip(), minor_digits=minor_digits)
    )
