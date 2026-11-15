"""Modal dialogs: generic forms, confirmations, help and the transaction editor."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, TypeVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Markdown, OptionList, Select, Static

from picciuli import Account, Book, Category, PicciuliError, Transaction
from picciuli_tui.formatting import MoneyFormat, category_label
from picciuli_tui.forms import (
    ENTRY_KIND_LABELS,
    NONE_ID,
    EntryKind,
    InputError,
    LineDraft,
    TransactionDraft,
    account_target,
    category_target,
    draft_from_transaction,
    line_totals,
    save_transaction,
    simple_lines,
)

T = TypeVar("T")

FormValues = dict[str, Any]


@dataclass(frozen=True)
class TextField:
    """A single-line text input of a `FormScreen`."""

    name: str
    label: str
    value: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class ChoiceField:
    """A drop-down choice of a `FormScreen`; `value` must be one of the options."""

    name: str
    label: str
    options: Sequence[tuple[str, Hashable]]
    value: Hashable


Field = TextField | ChoiceField


class FormInput(Input):
    """A one-line input without border, so that forms stay short."""

    def __init__(self, value: str = "", **kwargs: Any) -> None:
        super().__init__(value, compact=True, **kwargs)


class FormSelect(Select[T]):
    """A one-line drop-down without border, so that forms stay short."""

    def __init__(self, options: Iterable[tuple[str, T]], **kwargs: Any) -> None:
        super().__init__(options, compact=True, **kwargs)


def report_error(screen: ModalScreen[Any], error: Exception) -> None:
    """Show why an action failed, keeping the dialog open."""
    screen.notify(str(error), title="Cannot save", severity="error")


class FormScreen(ModalScreen[T], Generic[T]):
    """A dialog with labelled fields.

    On save the values are passed to `submit`; whatever it returns becomes the
    result of the dialog. If it raises a `PicciuliError` or an `InputError`, the
    message is shown and the dialog stays open. Cancelling returns `None`.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Save"),
    ]

    def __init__(
        self,
        title: str,
        fields: Sequence[Field],
        submit: Callable[[FormValues], T],
        *,
        help: str = "",
        save_label: str = "Save",
    ) -> None:
        super().__init__()
        self.form_title = title
        self.fields = fields
        self.submit = submit
        self.help = help
        self.save_label = save_label

    def compose(self) -> ComposeResult:
        """Lay out the fields in a two-column grid."""
        with Vertical(classes="dialog"):
            yield Label(self.form_title, classes="dialog-title")
            with Grid(classes="form-grid"):
                for item in self.fields:
                    yield Label(item.label)
                    if isinstance(item, TextField):
                        yield FormInput(
                            item.value,
                            placeholder=item.placeholder,
                            id=f"field-{item.name}",
                        )
                    else:
                        yield FormSelect(
                            item.options,
                            value=item.value,
                            allow_blank=False,
                            id=f"field-{item.name}",
                        )
            if self.help:
                yield Static(self.help, classes="form-help")
            with Horizontal(classes="buttons"):
                yield Button(self.save_label, variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def values(self) -> FormValues:
        """Return the current value of every field, by name."""
        result: FormValues = {}
        for item in self.fields:
            widget = self.query_one(f"#field-{item.name}")
            if isinstance(widget, (Input, Select)):
                result[item.name] = widget.value
        return result

    def action_submit(self) -> None:
        """Validate and apply the form."""
        try:
            result = self.submit(self.values())
        except (PicciuliError, InputError) as error:
            report_error(self, error)
            return
        self.dismiss(result)

    def action_cancel(self) -> None:
        """Close the dialog without changes."""
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Save when `enter` is pressed in a text field."""
        event.stop()
        self.action_submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the Save and Cancel buttons."""
        event.stop()
        if event.button.id == "save":
            self.action_submit()
        else:
            self.action_cancel()


class ConfirmScreen(ModalScreen[bool]):
    """Ask a yes/no question; `y` confirms, `n` or `escape` cancels."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "answer(True)", "Yes"),
        Binding("n,escape", "answer(False)", "No"),
    ]

    def __init__(self, question: str, *, confirm_label: str = "Delete") -> None:
        super().__init__()
        self.question = question
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        """Show the question and the two buttons."""
        with Vertical(classes="dialog"):
            yield Static(self.question, classes="question")
            with Horizontal(classes="buttons"):
                yield Button(f"{self.confirm_label} (y)", variant="error", id="yes")
                yield Button("Cancel (n)", id="no")

    def on_mount(self) -> None:
        """Focus the safe answer."""
        self.query_one("#no", Button).focus()

    def action_answer(self, answer: bool) -> None:
        """Close with the given answer."""
        self.dismiss(answer)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Answer with the pressed button."""
        event.stop()
        self.dismiss(event.button.id == "yes")


HELP = """\
# Picciuli keys

## Everywhere

| Key | Action |
|-----|--------|
| `1` … `5` or click a tab | Overview · Accounts · Categories · Periods · Budgets |
| `6` | Investments |
| `s` | Settings (currency, price provider, cost method) |
| `l` | Live prices on/off (refreshes market values periodically) |
| `?` | This help |
| `ctrl+p` | Command palette |
| `q` | Quit |
| `esc` | Back / close dialog |

## Lists

| Key | Action |
|-----|--------|
| `↑` `↓` or `j` `k` | Move |
| `n` | New |
| `enter` or `e` | Open / edit |
| `d` or `del` | Delete (asks first) |
| `shift+↑` `shift+↓` | Reorder (accounts, categories) |

## Overview

| Key | Action |
|-----|--------|
| `←` `→` `↑` `↓` | Previous / next day, week |
| `pgup` `pgdn` | Previous / next month (also the mouse wheel) |
| `t` | Today |
| `g` | Go to a date |
| `tab` | Switch between calendar and day list |
| `n` | New transaction on the selected day |
| `[` `]` | Previous / next period covering the day |
| `p` | Start a period on the selected day |

## Accounts and budgets

| Key | Action |
|-----|--------|
| `enter` | Open the account register |
| `c` | Close / reopen an account |
| `[` `]` | Previous / next period (budgets) |
| `y` | Copy budgets from another period |

## Investments

| Key | Action |
|-----|--------|
| `tab` | Switch between holdings and securities |
| `n` / `e` / `d` | New / edit / delete security |
| `f` | Find a security by name, symbol or ISIN |
| `b` / `x` | Buy / sell shares |
| `p` | Enter a price by hand |
| `r` | Refresh prices now |
| `h` | Download price history since the first purchase |

## Forms

`tab` / `shift+tab` move between fields, `enter` or `ctrl+s` saves and `esc`
cancels. Dates accept `2025-02-03`, `3/2/2025`, `3/2`, `3`, `today`, `+1`, `-7`.
"""


class HelpScreen(ModalScreen[None]):
    """The list of keys."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,question_mark,q", "close", "Close")
    ]

    def compose(self) -> ComposeResult:
        """Show the key reference."""
        with VerticalScroll(classes="dialog help"):
            yield Markdown(HELP)

    def action_close(self) -> None:
        """Close the help."""
        self.dismiss(None)


class PickScreen(ModalScreen[T], Generic[T]):
    """Choose one item of a list; `enter` picks, `escape` returns `None`."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, items: Sequence[tuple[str, T]]) -> None:
        super().__init__()
        self.pick_title = title
        self.items = items

    def compose(self) -> ComposeResult:
        """Show the items."""
        with Vertical(classes="dialog wide"):
            yield Label(self.pick_title, classes="dialog-title")
            yield OptionList(*(label for label, _ in self.items), id="pick")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Return the chosen item."""
        event.stop()
        self.dismiss(self.items[event.option_index][1])

    def action_cancel(self) -> None:
        """Close without choosing."""
        self.dismiss(None)


# Transaction editor

SPLIT_HELP = (
    "Account lines: balance change (+ in, − out). Other lines: income (+) or "
    "expense (−) by category. Both totals must match."
)


class SplitLineRow(Horizontal):
    """One editable split line: target, signed amount, memo and a remove button."""

    def __init__(self, targets: Sequence[tuple[str, str]], line: LineDraft) -> None:
        super().__init__(classes="split-line")
        self.targets = targets
        self.line = line

    def compose(self) -> ComposeResult:
        """Show the line widgets."""
        known = {value for _, value in self.targets}
        yield FormSelect(
            self.targets,
            value=self.line.target if self.line.target in known else Select.NULL,
            prompt="Account or category",
            classes="line-target",
        )
        yield FormInput(self.line.amount, placeholder="±amount", classes="line-amount")
        if self.line.security_id is not None:
            yield Static(
                f"{self.line.quantity} sh", classes="line-shares", markup=False
            )
        yield FormInput(self.line.memo, placeholder="memo", classes="line-memo")
        yield Button("✕", compact=True, classes="line-remove")

    def draft(self) -> LineDraft:
        """Return the line as typed (shares moved by the line are kept as is)."""
        target = self.query_one(".line-target", Select).value
        return LineDraft(
            target if isinstance(target, str) else "",
            self.query_one(".line-amount", Input).value,
            self.query_one(".line-memo", Input).value,
            self.line.security_id,
            self.line.quantity,
        )


class TransactionForm(ModalScreen[bool]):
    """Create or edit a transaction. The result is `True` once saved."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+n", "add_line", "Add split line"),
    ]

    def __init__(
        self,
        book: Book,
        money: MoneyFormat,
        *,
        today: dt.date,
        day: dt.date,
        transaction: Transaction | None = None,
        account_id: int | None = None,
    ) -> None:
        super().__init__()
        self.book = book
        self.money = money
        self.today = today
        self.transaction = transaction
        accounts = book.accounts.list()
        used = (
            {s.account_id for s in transaction.account_splits} if transaction else set()
        )
        self.accounts: list[Account] = [
            a for a in accounts if not a.is_closed or a.id in used
        ]
        self.categories: list[Category] = book.categories.list()
        if transaction is not None:
            self.draft = draft_from_transaction(transaction, money)
        else:
            default = account_id or (self.accounts[0].id if self.accounts else None)
            self.draft = TransactionDraft(date=day.isoformat(), account_id=default)

    # Options

    def _account_options(self) -> list[tuple[str, int]]:
        return [
            (f"{a.name} (closed)" if a.is_closed else a.name, a.id)
            for a in self.accounts
        ]

    def _category_options(self) -> list[tuple[str, int]]:
        by_id = {c.id: c for c in self.categories}
        return [("Uncategorized", NONE_ID)] + [
            (category_label(c.id, by_id), c.id) for c in self.categories
        ]

    def _targets(self) -> list[tuple[str, str]]:
        by_id = {c.id: c for c in self.categories}
        return (
            [
                (f"Account · {name}", account_target(i))
                for name, i in self._account_options()
            ]
            + [("Uncategorized", category_target(None))]
            + [
                (f"Category · {category_label(c.id, by_id)}", category_target(c.id))
                for c in self.categories
            ]
        )

    @staticmethod
    def _choice(options: Sequence[tuple[str, int]], value: int | None) -> int | Any:
        return value if value in {v for _, v in options} else Select.NULL

    # Layout

    def compose(self) -> ComposeResult:
        """Lay out the common fields, the simple fields and the split editor."""
        draft = self.draft
        accounts = self._account_options()
        categories = self._category_options()
        title = "Edit transaction" if self.transaction else "New transaction"
        with Vertical(classes="dialog wide"):
            yield Label(title, classes="dialog-title")
            with Grid(classes="form-grid"):
                yield Label("Kind")
                yield FormSelect(
                    [(label, kind) for kind, label in ENTRY_KIND_LABELS.items()],
                    value=draft.kind,
                    allow_blank=False,
                    id="kind",
                )
                yield Label("Date")
                yield FormInput(draft.date, placeholder="YYYY-MM-DD", id="date")
                yield Label("Amount", classes="simple")
                yield FormInput(
                    draft.amount, placeholder="0.00", id="amount", classes="simple"
                )
                yield Label("Account", id="account-label", classes="simple")
                yield FormSelect(
                    accounts,
                    value=self._choice(accounts, draft.account_id),
                    prompt="Choose an account",
                    id="account",
                    classes="simple",
                )
                yield Label("Category", classes="flow")
                yield FormSelect(
                    categories,
                    value=self._choice(categories, draft.category_id or NONE_ID),
                    allow_blank=False,
                    id="category",
                    classes="flow",
                )
                yield Label("To account", classes="transfer")
                yield FormSelect(
                    accounts,
                    value=self._choice(accounts, draft.to_account_id),
                    prompt="Choose an account",
                    id="to-account",
                    classes="transfer",
                )
            with Vertical(id="split-editor"):
                yield Static(SPLIT_HELP, classes="form-help")
                with VerticalScroll(id="lines"):
                    for line in draft.lines:
                        yield SplitLineRow(self._targets(), line)
                with Horizontal(classes="split-footer"):
                    yield Button("+ Add line (ctrl+n)", compact=True, id="add-line")
                    yield Static(id="difference")
            with Grid(classes="form-grid"):
                yield Label("Description")
                yield FormInput(draft.description, id="description")
                yield Label("Notes")
                yield FormInput(draft.notes, id="notes")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        """Show the widgets of the current kind and focus the first useful field."""
        self._show_kind(self.draft.kind)
        if self.draft.kind is not EntryKind.SPLIT:
            self.query_one("#amount", Input).focus()

    def kind(self) -> EntryKind:
        """Return the selected kind."""
        value = self.query_one("#kind", Select).value
        return value if isinstance(value, EntryKind) else EntryKind.EXPENSE

    def _show_kind(self, kind: EntryKind) -> None:
        simple = kind is not EntryKind.SPLIT
        for widget in self.query(".simple"):
            widget.display = simple
        for widget in self.query(".flow"):
            widget.display = kind in (EntryKind.EXPENSE, EntryKind.INCOME)
        for widget in self.query(".transfer"):
            widget.display = kind is EntryKind.TRANSFER
        self.query_one("#account-label", Label).update(
            "From account" if kind is EntryKind.TRANSFER else "Account"
        )
        self.query_one("#split-editor").display = not simple
        self.update_difference()

    # Reading the form

    def _select_id(self, selector: str) -> int | None:
        value = self.query_one(selector, Select).value
        return value if isinstance(value, int) else None

    def lines(self) -> list[LineDraft]:
        """Return the split lines as typed."""
        return [row.draft() for row in self.query(SplitLineRow)]

    def current_draft(self) -> TransactionDraft:
        """Return the whole form as a draft."""
        return TransactionDraft(
            kind=self.kind(),
            date=self.query_one("#date", Input).value,
            description=self.query_one("#description", Input).value,
            notes=self.query_one("#notes", Input).value,
            amount=self.query_one("#amount", Input).value,
            account_id=self._select_id("#account"),
            category_id=self._select_id("#category"),
            to_account_id=self._select_id("#to-account"),
            lines=self.lines(),
        )

    def update_difference(self) -> None:
        """Show the account and external totals of the split lines."""
        accounts, external = line_totals(self.lines(), self.money)
        difference = accounts - external
        label = self.query_one("#difference", Static)
        totals = (
            f"Accounts {self.money.amount(accounts)} · "
            f"Other {self.money.amount(external)}"
        )
        if difference:
            label.update(f"{totals} · [b red]Off by {self.money.amount(difference)}[/]")
        else:
            label.update(f"{totals} · [b green]Balanced[/]")

    # Events and actions

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Switch kind (pre-filling split lines) or refresh the totals."""
        if event.select.id == "kind":
            kind = self.kind()
            if kind is EntryKind.SPLIT and not self.query(SplitLineRow):
                previous = self.current_draft()
                previous.kind = self.draft.kind
                container = self.query_one("#lines", VerticalScroll)
                await container.mount_all(
                    SplitLineRow(self._targets(), line)
                    for line in simple_lines(previous, self.money)
                )
            if kind is not EntryKind.SPLIT:
                self.draft.kind = kind
            self._show_kind(kind)
        else:
            self.update_difference()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refresh the totals while amounts are typed."""
        if event.input.has_class("line-amount"):
            self.update_difference()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Save when `enter` is pressed in a text field."""
        event.stop()
        self.action_save()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle save, cancel, add-line and remove-line buttons."""
        event.stop()
        if event.button.id == "save":
            self.action_save()
        elif event.button.id == "cancel":
            self.action_cancel()
        elif event.button.id == "add-line":
            await self.action_add_line()
        elif event.button.has_class("line-remove"):
            row = event.button.parent
            if isinstance(row, SplitLineRow):
                await row.remove()
            self.update_difference()

    async def action_add_line(self) -> None:
        """Append an empty split line (switching to the split editor if needed)."""
        if self.kind() is not EntryKind.SPLIT:
            self.query_one("#kind", Select).value = EntryKind.SPLIT
            return
        row = SplitLineRow(self._targets(), LineDraft())
        await self.query_one("#lines", VerticalScroll).mount(row)
        row.query_one(".line-target", Select).focus()
        self.update_difference()

    def action_save(self) -> None:
        """Validate and store the transaction."""
        try:
            save_transaction(
                self.book,
                self.current_draft(),
                self.money,
                today=self.today,
                transaction_id=self.transaction.id if self.transaction else None,
            )
        except (PicciuliError, InputError) as error:
            report_error(self, error)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        """Close without saving."""
        self.dismiss(False)
