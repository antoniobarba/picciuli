"""The overview: calendar, the selected day's transactions and the period."""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Static

from picciuli import (
    Account,
    BudgetReport,
    Category,
    Period,
    PeriodSummary,
    Transaction,
    TransactionKind,
)
from picciuli_tui.calendar_model import (
    choose_period,
    cycle_period,
    load_month,
    shift_month,
)
from picciuli_tui.formatting import (
    long_date,
    period_range,
    transaction_accounts,
    transaction_category,
    transaction_title,
)
from picciuli_tui.forms import default_period_name, parse_date, save_period
from picciuli_tui.screens.base import BookScreen
from picciuli_tui.screens.modals import (
    ConfirmScreen,
    FormScreen,
    FormValues,
    TextField,
    TransactionForm,
)
from picciuli_tui.widgets import CalendarWidget, ListTable, amount_text


class OverviewScreen(BookScreen):
    """Month calendar on the left; day transactions and period details on the right."""

    SUB_TITLE = "Overview"
    MODE = "overview"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "new_transaction", "New"),
        Binding("e", "edit_transaction", "Edit"),
        Binding("d,delete", "delete_transaction", "Delete"),
        Binding("t", "today", "Today"),
        Binding("g", "go_to", "Go to"),
        Binding("left_square_bracket", "cycle_period(-1)", "◂Period"),
        Binding("right_square_bracket", "cycle_period(1)", "Period▸"),
        Binding("p", "new_period", "Start period"),
        Binding("pageup", "month(-1)", "Month", show=False),
        Binding("pagedown", "month(1)", "Month", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.day: dt.date | None = None
        self.period_id: int | None = None
        self.transactions: list[Transaction] = []

    def compose(self) -> ComposeResult:
        """Build the two panes."""
        today = self.today()
        yield from self.top_bar()
        with Horizontal(id="overview"):
            with Vertical(id="calendar-pane"):
                yield Static(id="period-title")
                yield CalendarWidget(today, money=self.money, id="calendar")
                yield Static(id="period-totals")
            with Vertical(id="detail-pane"):
                yield Static(id="day-title", classes="pane-title")
                yield ListTable(id="day-list")
                with VerticalScroll(id="period-scroll"):
                    yield Static(id="period-panel")
        yield Footer()

    def on_mount(self) -> None:
        """Set up the day list columns and focus the calendar."""
        table = self.query_one("#day-list", ListTable)
        table.add_column("Description", key="description")
        table.add_column("Accounts", key="accounts")
        table.add_column("Category", key="category")
        table.add_column("Amount", key="amount")
        self.query_one(CalendarWidget).focus()

    # Data

    @property
    def selected_day(self) -> dt.date:
        """The day selected in the calendar (today until the user moves)."""
        if self.day is None:
            self.day = self.today()
        return self.day

    def select_day(self, day: dt.date) -> None:
        """Select another day and refresh everything."""
        self.day = day
        self.reload()

    def reload(self) -> None:
        """Read the book and update every pane."""
        book, money, day = self.book, self.money, self.selected_day
        accounts = {a.id: a for a in book.accounts.list()}
        categories = {c.id: c for c in book.categories.list()}
        covering = book.periods.periods_on(day)
        period = choose_period(covering, self.period_id)
        self.period_id = period.id if period else None
        self.query_one(CalendarWidget).show(
            day,
            today=self.today(),
            flows=load_month(book, day.year, day.month),
            band=period,
            money=money,
        )
        self.transactions = book.transactions.list(start=day, end=day)
        summary = book.periods.summary(period.id) if period else None
        budgets = book.budgets.report(period.id) if period else None
        self._show_period_title(period, covering)
        self._show_period_totals(summary)
        self._show_day(day, accounts, categories)
        self._show_period_panel(day, accounts, summary, budgets)

    # Rendering

    def _show_period_title(self, period: Period | None, covering: list[Period]) -> None:
        title = self.query_one("#period-title", Static)
        if period is None:
            title.update(
                Text.from_markup("[b]No period[/] covers this day · [b]p[/] start one")
            )
            return
        text = Text.from_markup(f"[b]{period.name}[/]  {period_range(period)}")
        if len(covering) > 1:
            index = list(reversed(covering)).index(period) + 1
            text.append(f"  [{index}/{len(covering)}] [ ] to switch", style="dim")
        title.update(text)

    def _show_period_totals(self, summary: PeriodSummary | None) -> None:
        totals = self.query_one("#period-totals", Static)
        if summary is None:
            totals.update("")
            return
        text = Text()
        for label, value in (
            ("Income ", summary.income),
            ("   Expenses ", summary.expenses),
            ("   Net ", summary.net),
        ):
            text.append(label, style="dim")
            text.append_text(
                amount_text(self.money, value, plus=label.strip() == "Net")
            )
        totals.update(text)

    def _show_day(
        self,
        day: dt.date,
        accounts: dict[int, Account],
        categories: dict[int, Category],
    ) -> None:
        count = len(self.transactions)
        label = f"[b]{long_date(day)}[/]"
        if day == self.today():
            label += " · today"
        label += f" · {count} transaction{'s' if count != 1 else ''}"
        if not accounts:
            label += " · [b]2[/] Accounts → [b]n[/] to create your first account"
        self.query_one("#day-title", Static).update(Text.from_markup(label))
        table = self.query_one("#day-list", ListTable)
        selected = table.selected_key()
        table.clear()
        for transaction in self.transactions:
            if transaction.kind is TransactionKind.TRANSFER:
                moved = sum(
                    s.amount for s in transaction.account_splits if s.amount > 0
                )
                amount = Text(self.money.amount(moved), style="dim", justify="right")
            else:
                amount = amount_text(self.money, transaction.net_amount)
            table.add_row(
                transaction_title(transaction),
                transaction_accounts(transaction, accounts),
                transaction_category(transaction, categories),
                amount,
                key=str(transaction.id),
            )
        table.select_key(selected)

    def _show_period_panel(
        self,
        day: dt.date,
        accounts: dict[int, Account],
        summary: PeriodSummary | None,
        budgets: BudgetReport | None,
    ) -> None:
        money = self.money
        panel = Table.grid(padding=(0, 2), expand=True)
        panel.add_column("name", ratio=1, no_wrap=True, overflow="ellipsis")
        panel.add_column("actual", justify="right", no_wrap=True)
        panel.add_column("budget", justify="right", no_wrap=True)
        panel.add_column("left", justify="right", no_wrap=True)
        if summary is not None:
            lines = (
                {line.category.id: line for line in budgets.lines} if budgets else {}
            )
            panel.add_row(
                Text("Category", style="b"),
                Text("Actual", style="b"),
                Text("Budget", style="b"),
                Text("Left", style="b"),
            )
            for item in summary.categories:
                line = lines.get(item.category.id)
                value = item.total
                if not value and line is None:
                    continue
                name = (
                    f"  └ {item.category.name}"
                    if item.category.parent_id is not None
                    else item.category.name
                )
                panel.add_row(
                    name,
                    amount_text(money, value),
                    money.amount(line.budget.amount) if line else "",
                    amount_text(money, line.remaining) if line else "",
                )
            if summary.uncategorized:
                panel.add_row(
                    Text("Uncategorized", style="italic"),
                    amount_text(money, summary.uncategorized),
                    "",
                    "",
                )
            if budgets is not None and budgets.lines:
                panel.add_row(
                    Text("Budgeted total", style="b"),
                    amount_text(money, budgets.total_actual, bold=True),
                    Text(money.amount(budgets.total_budget), style="b"),
                    amount_text(money, budgets.total_remaining, bold=True),
                )
            panel.add_row("")
        panel.add_row(
            Text("Balances", style="b"), Text(f"{day:%d %b %Y}", style="dim"), "", ""
        )
        for balance in self.book.accounts.balances(as_of=day):
            panel.add_row(
                f"  {balance.account.name}", amount_text(money, balance.balance), "", ""
            )
        if accounts:
            worth = self.book.accounts.net_worth(as_of=day)
            panel.add_row(
                Text("Net worth", style="b"),
                amount_text(money, worth.net_worth, bold=True),
                "",
                "",
            )
        self.query_one("#period-panel", Static).update(panel)

    # Calendar events and navigation actions

    def on_calendar_widget_day_requested(
        self, message: CalendarWidget.DayRequested
    ) -> None:
        """Follow the calendar selection."""
        self.select_day(message.day)

    def on_data_table_row_selected(self, message: ListTable.RowSelected) -> None:
        """Edit the transaction picked with `enter`."""
        message.stop()
        self.action_edit_transaction()

    def action_today(self) -> None:
        """Jump to today."""
        self.select_day(self.today())

    def action_month(self, months: int) -> None:
        """Move by whole months."""
        self.select_day(shift_month(self.selected_day, months))

    def action_cycle_period(self, step: int) -> None:
        """Show the previous or next period covering the selected day."""
        covering = self.book.periods.periods_on(self.selected_day)
        if len(covering) < 2:
            self.notify("No other period covers this day.")
            return
        period = cycle_period(covering, self.period_id, step)
        self.period_id = period.id if period else None
        self.reload()

    def action_go_to(self) -> None:
        """Ask for a date and jump to it."""
        today = self.today()

        def submit(values: FormValues) -> dt.date:
            return parse_date(values["date"], today=today)

        self.app.push_screen(
            FormScreen(
                "Go to date",
                [TextField("date", "Date", self.selected_day.isoformat())],
                submit,
                save_label="Go",
                help="2025-02-03, 3/2/2025, 3/2, 3, today, +7, -30",
            ),
            self._go_to_result,
        )

    def _go_to_result(self, day: dt.date | None) -> None:
        if day is not None:
            self.select_day(day)

    # Transactions

    def selected_transaction(self) -> Transaction | None:
        """Return the transaction under the day list cursor."""
        key = self.query_one("#day-list", ListTable).selected_key()
        return next((t for t in self.transactions if str(t.id) == key), None)

    def action_new_transaction(self) -> None:
        """Record a transaction on the selected day."""
        if not self.book.accounts.list(include_closed=False):
            self.notify(
                "Create an account first: press 2, then n.",
                title="No accounts",
                severity="warning",
            )
            return
        self.app.push_screen(
            TransactionForm(
                self.book, self.money, today=self.today(), day=self.selected_day
            )
        )

    def action_edit_transaction(self) -> None:
        """Edit the selected transaction."""
        transaction = self.selected_transaction()
        if transaction is None:
            self.notify("No transaction selected on this day.")
            return
        self.app.push_screen(
            TransactionForm(
                self.book,
                self.money,
                today=self.today(),
                day=self.selected_day,
                transaction=transaction,
            )
        )

    def action_delete_transaction(self) -> None:
        """Delete the selected transaction after confirmation."""
        transaction = self.selected_transaction()
        if transaction is None:
            self.notify("No transaction selected on this day.")
            return

        def confirmed(answer: bool | None) -> None:
            if answer and self.attempt(
                lambda: self.book.transactions.delete(transaction.id)
            ):
                self.reload()

        self.app.push_screen(
            ConfirmScreen(f"Delete “{transaction_title(transaction)}”?"), confirmed
        )

    # Periods

    def action_new_period(self) -> None:
        """Start a period on the selected day."""
        day, today = self.selected_day, self.today()

        def submit(values: FormValues) -> Period:
            return save_period(
                self.book,
                name=values["name"],
                start=values["start"],
                end=values["end"],
                today=today,
            )

        self.app.push_screen(
            FormScreen(
                "Start a period",
                [
                    TextField("name", "Name", placeholder=default_period_name(day)),
                    TextField("start", "Start", day.isoformat()),
                    TextField("end", "End", placeholder="empty = open-ended"),
                ],
                submit,
                help=(
                    "An open-ended period lasts until the next open-ended period "
                    "starts: starting one closes the earlier ones the day before."
                ),
            ),
            self._period_created,
        )

    def _period_created(self, period: Period | None) -> None:
        if period is not None:
            self.period_id = period.id
            self.reload()
