"""Accounts list and the register (ledger) of one account."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Footer, Static

from picciuli import Account, Category, Register, Transaction
from picciuli_tui.formatting import (
    ACCOUNT_TYPE_LABELS,
    account_change,
    account_name,
    progress_bar,
    short_date,
    transaction_category,
    transaction_title,
)
from picciuli_tui.forms import AccountDraft, parse_date, save_account
from picciuli_tui.screens.base import BookScreen
from picciuli_tui.screens.modals import (
    ChoiceField,
    ConfirmScreen,
    FormScreen,
    FormValues,
    TextField,
    TransactionForm,
    trade_form,
)
from picciuli_tui.widgets import ListTable, amount_text


class AccountsScreen(BookScreen):
    """Every account with its balance, goal and state."""

    SUB_TITLE = "Accounts"
    MODE = "accounts"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "new", "New"),
        Binding("e", "edit", "Edit"),
        Binding("d,delete", "delete", "Delete"),
        Binding("c", "close_or_reopen", "Close/reopen"),
        Binding("shift+up", "move(-1)", "Move up", show=False),
        Binding("shift+down", "move(1)", "Move down", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.accounts: list[Account] = []

    def compose(self) -> ComposeResult:
        """Build the table."""
        yield from self.top_bar()
        yield Static(
            "[b]Accounts[/] · enter opens the register · shift+↑/↓ reorders",
            classes="pane-title",
        )
        yield ListTable(id="accounts")
        yield Static(id="accounts-total", classes="pane-footer")
        yield Footer()

    def on_mount(self) -> None:
        """Add the columns."""
        table = self.query_one(ListTable)
        for label in (
            "Name",
            "Type",
            "Balance",
            "Market value",
            "Goal",
            "Progress",
            "State",
        ):
            table.add_column(label, key=label.lower())

    def reload(self) -> None:
        """Read accounts, balances and the market value of investments."""
        money = self.money
        self.accounts = self.book.accounts.list()
        balances = {
            b.account.id: b.balance
            for b in self.book.accounts.balances(include_closed=True)
        }
        market = {
            v.account.id: v.market_value
            for v in self.book.investments.valuations(include_closed=True)
        }
        table = self.query_one(ListTable)
        selected = table.selected_key()
        table.clear()
        for account in self.accounts:
            balance = balances.get(account.id, 0)
            progress = ""
            if account.goal:
                fraction = market.get(account.id, balance) / account.goal
                progress = f"{progress_bar(fraction)} {fraction:4.0%}"
            table.add_row(
                Text(account.name, style="dim" if account.is_closed else ""),
                ACCOUNT_TYPE_LABELS[account.type],
                amount_text(money, balance),
                amount_text(money, market[account.id]) if account.id in market else "",
                money.amount(account.goal) if account.goal is not None else "",
                progress,
                f"closed {short_date(account.closed_on)}" if account.closed_on else "",
                key=str(account.id),
            )
        table.select_key(selected)
        worth = self.book.investments.net_worth()
        total = Text()
        for label, value in (
            ("Assets ", worth.assets),
            ("   Liabilities ", worth.liabilities),
            ("   Net worth ", worth.net_worth),
        ):
            total.append(label, style="dim")
            total.append_text(amount_text(money, value))
        if market:
            total.append("   (investments at market value)", style="dim")
        self.query_one("#accounts-total", Static).update(total)

    def selected(self) -> Account | None:
        """Return the account under the cursor."""
        key = self.query_one(ListTable).selected_key()
        return next((a for a in self.accounts if str(a.id) == key), None)

    def on_data_table_row_selected(self, message: ListTable.RowSelected) -> None:
        """Open the register of the account picked with `enter`."""
        message.stop()
        account = self.selected()
        if account is not None:
            self.app.push_screen(RegisterScreen(account.id))

    def _form(self, account: Account | None) -> None:
        money, today = self.money, self.today()
        draft = AccountDraft.of(account, money) if account else AccountDraft()

        def submit(values: FormValues) -> Account:
            return save_account(
                self.book,
                AccountDraft(
                    name=values["name"],
                    type=values["type"],
                    opening_balance=values["opening_balance"],
                    opening_date=values["opening_date"],
                    goal=values["goal"],
                    notes=values["notes"],
                ),
                money,
                today=today,
                account_id=account.id if account else None,
            )

        self.app.push_screen(
            FormScreen(
                f"Edit {account.name}" if account else "New account",
                [
                    TextField("name", "Name", draft.name),
                    ChoiceField(
                        "type",
                        "Type",
                        [(label, kind) for kind, label in ACCOUNT_TYPE_LABELS.items()],
                        draft.type,
                    ),
                    TextField(
                        "opening_balance",
                        "Opening balance",
                        draft.opening_balance,
                        "0.00",
                    ),
                    TextField(
                        "opening_date", "Opening date", draft.opening_date, "optional"
                    ),
                    TextField("goal", "Goal", draft.goal, "optional target balance"),
                    TextField("notes", "Notes", draft.notes),
                ],
                submit,
                help=(
                    "Liabilities (cards, loans, mortgages) have negative balances "
                    "while you owe money: enter a mortgage of 150,000 as -150000."
                ),
            )
        )

    def action_new(self) -> None:
        """Create an account."""
        self._form(None)

    def action_edit(self) -> None:
        """Edit the selected account."""
        account = self.selected()
        if account is not None:
            self._form(account)

    def action_delete(self) -> None:
        """Delete the selected (never used) account."""
        account = self.selected()
        if account is None:
            return

        def confirmed(answer: bool | None) -> None:
            if answer and self.attempt(lambda: self.book.accounts.delete(account.id)):
                self.reload()

        self.app.push_screen(
            ConfirmScreen(
                f"Delete account “{account.name}”?\n"
                "Only accounts without transactions can be deleted; close the others."
            ),
            confirmed,
        )

    def action_close_or_reopen(self) -> None:
        """Close an open account on a chosen day, or reopen a closed one."""
        account = self.selected()
        if account is None:
            return
        if account.is_closed:

            def reopen(answer: bool | None) -> None:
                if answer and self.attempt(
                    lambda: self.book.accounts.reopen(account.id)
                ):
                    self.reload()

            self.app.push_screen(
                ConfirmScreen(f"Reopen “{account.name}”?", confirm_label="Reopen"),
                reopen,
            )
            return
        today = self.today()

        def submit(values: FormValues) -> Account:
            day = parse_date(values["on"], today=today)
            return self.book.accounts.close(account.id, on=day)

        self.app.push_screen(
            FormScreen(
                f"Close {account.name}",
                [TextField("on", "Closing date", today.isoformat())],
                submit,
                save_label="Close account",
                help="The balance must be zero. A closed account keeps its history.",
            )
        )

    def action_move(self, step: int) -> None:
        """Move the selected account up or down."""
        account = self.selected()
        if account is None:
            return
        position = min(max(account.position + step, 1), len(self.accounts))
        if self.attempt(lambda: self.book.accounts.move(account.id, position)):
            self.reload()


class RegisterScreen(BookScreen):
    """The transactions of one account with the running balance."""

    MODE = "accounts"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back"),
        Binding("n", "new", "New"),
        Binding("e", "edit", "Edit"),
        Binding("d,delete", "delete", "Delete"),
    ]

    def __init__(self, account_id: int) -> None:
        super().__init__()
        self.account_id = account_id
        self.register: Register | None = None
        self.first_load = True

    def compose(self) -> ComposeResult:
        """Build the table."""
        yield from self.top_bar()
        yield Static(id="register-title", classes="pane-title")
        yield ListTable(id="register")
        yield Footer()

    def on_mount(self) -> None:
        """Add the columns."""
        table = self.query_one(ListTable)
        for label in ("Date", "Description", "Details", "Amount", "Balance"):
            table.add_column(label, key=label.lower())

    def reload(self) -> None:
        """Read the register."""
        money = self.money
        register = self.register = self.book.accounts.register(self.account_id)
        account = register.account
        self.sub_title = f"Register · {account.name}"
        accounts = {a.id: a for a in self.book.accounts.list()}
        categories = {c.id: c for c in self.book.categories.list()}
        title = Text.from_markup(
            f"[b]{account.name}[/] · {ACCOUNT_TYPE_LABELS[account.type]} · "
            f"starting balance {money.amount(register.starting_balance)} · balance "
        )
        title.append_text(amount_text(money, register.ending_balance, bold=True))
        if account.is_closed:
            title.append(" · closed", style="dim")
        self.query_one("#register-title", Static).update(title)
        table = self.query_one(ListTable)
        selected = table.selected_key()
        table.clear()
        for entry in register.entries:
            transaction = entry.transaction
            table.add_row(
                short_date(transaction.date),
                transaction_title(transaction),
                self._details(transaction, accounts, categories),
                amount_text(money, entry.amount),
                amount_text(money, entry.balance),
                key=str(transaction.id),
            )
        if self.first_load and table.row_count:
            table.move_cursor(row=table.row_count - 1)
            self.first_load = False
        else:
            table.select_key(selected)

    def _details(
        self,
        transaction: Transaction,
        accounts: dict[int, Account],
        categories: dict[int, Category],
    ) -> str:
        others = [
            s for s in transaction.account_splits if s.account_id != self.account_id
        ]
        if transaction.external_splits:
            label = transaction_category(transaction, categories)
            if others:
                names = ", ".join(account_name(s.account_id, accounts) for s in others)
                label += f" + {names}"
            return label
        mine = account_change(transaction, self.account_id)
        arrow = "→" if mine < 0 else "←"
        return f"{arrow} " + ", ".join(
            account_name(s.account_id, accounts) for s in others
        )

    def selected(self) -> Transaction | None:
        """Return the transaction under the cursor."""
        key = self.query_one(ListTable).selected_key()
        if self.register is None or key is None:
            return None
        return next(
            (
                e.transaction
                for e in self.register.entries
                if str(e.transaction.id) == key
            ),
            None,
        )

    def on_data_table_row_selected(self, message: ListTable.RowSelected) -> None:
        """Edit the transaction picked with `enter`."""
        message.stop()
        self.action_edit()

    def action_back(self) -> None:
        """Return to the accounts list."""
        self.app.pop_screen()

    def action_new(self) -> None:
        """Record a transaction on this account, dated today."""
        today = self.today()
        self.app.push_screen(
            TransactionForm(
                self.book,
                self.money,
                today=today,
                day=today,
                account_id=self.account_id,
            )
        )

    def action_edit(self) -> None:
        """Edit the selected transaction."""
        transaction = self.selected()
        if transaction is None:
            return
        form = trade_form(
            self.book,
            self.money,
            today=self.today(),
            transaction=transaction,
        )
        self.app.push_screen(
            form
            or TransactionForm(
                self.book,
                self.money,
                today=self.today(),
                day=transaction.date,
                transaction=transaction,
            )
        )

    def action_delete(self) -> None:
        """Delete the selected transaction after confirmation."""
        transaction = self.selected()
        if transaction is None:
            return

        def confirmed(answer: bool | None) -> None:
            if answer and self.attempt(
                lambda: self.book.transactions.delete(transaction.id)
            ):
                self.reload()

        self.app.push_screen(
            ConfirmScreen(
                f"Delete “{transaction_title(transaction)}” of "
                f"{transaction.date:%d %b %Y}?"
            ),
            confirmed,
        )
