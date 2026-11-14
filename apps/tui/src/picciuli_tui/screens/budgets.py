"""Budgets of one period compared with the actual flows."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Footer, Static

from picciuli import BudgetLine, Period
from picciuli_tui.calendar_model import choose_period
from picciuli_tui.formatting import category_label, period_range, progress_bar
from picciuli_tui.forms import save_budget
from picciuli_tui.screens.base import BookScreen
from picciuli_tui.screens.modals import (
    ChoiceField,
    ConfirmScreen,
    FormScreen,
    FormValues,
    TextField,
)
from picciuli_tui.widgets import ListTable, amount_text


class BudgetsScreen(BookScreen):
    """The budget report of a period; `[` and `]` change period."""

    SUB_TITLE = "Budgets"
    MODE = "budgets"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left_square_bracket", "period(-1)", "◂Period"),
        Binding("right_square_bracket", "period(1)", "Period▸"),
        Binding("n", "new", "New"),
        Binding("e", "edit", "Edit"),
        Binding("d,delete", "delete", "Delete"),
        Binding("y", "copy", "Copy from…"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.period_id: int | None = None
        self.periods: list[Period] = []
        self.lines: list[BudgetLine] = []

    def compose(self) -> ComposeResult:
        """Build the table."""
        yield from self.top_bar()
        yield Static(id="budget-title", classes="pane-title")
        yield ListTable(id="budgets")
        yield Static(id="budget-total", classes="pane-footer")
        yield Footer()

    def on_mount(self) -> None:
        """Add the columns."""
        table = self.query_one(ListTable)
        for label in ("Category", "Budget", "Actual", "Remaining", "Used"):
            table.add_column(label, key=label.lower())

    @property
    def period(self) -> Period | None:
        """The period whose budgets are shown."""
        return next((p for p in self.periods if p.id == self.period_id), None)

    def reload(self) -> None:
        """Read the budget report of the selected period."""
        money = self.money
        self.periods = self.book.periods.list()
        if self.period is None:
            current = choose_period(self.book.periods.periods_on(self.today()), None)
            chosen = current or (self.periods[-1] if self.periods else None)
            self.period_id = chosen.id if chosen else None
        table = self.query_one(ListTable)
        selected = table.selected_key()
        table.clear()
        period = self.period
        title = self.query_one("#budget-title", Static)
        total = self.query_one("#budget-total", Static)
        if period is None:
            self.lines = []
            title.update(
                Text.from_markup("[b]Budgets[/] · no periods yet: press 4, then n")
            )
            total.update("")
            return
        index = self.periods.index(period) + 1
        title.update(
            Text.from_markup(
                f"[b]Budgets · {period.name}[/]  {period_range(period)}"
                f"  [dim]{index}/{len(self.periods)} · [ ] change period[/]"
            )
        )
        report = self.book.budgets.report(period.id)
        self.lines = list(report.lines)
        categories = {c.id: c for c in self.book.categories.list()}
        for line in self.lines:
            used = ""
            if line.budget.amount > 0:
                fraction = -line.actual / line.budget.amount
                used = f"{progress_bar(fraction)} {fraction:4.0%}"
            table.add_row(
                category_label(line.category.id, categories),
                money.amount(line.budget.amount),
                amount_text(money, line.actual),
                amount_text(money, line.remaining),
                Text(used, style="red" if line.remaining < 0 else ""),
                key=str(line.budget.id),
            )
        table.select_key(selected)
        summary = Text()
        for label, value in (
            ("Budget ", report.total_budget),
            ("   Actual ", report.total_actual),
            ("   Remaining ", report.total_remaining),
        ):
            summary.append(label, style="dim")
            summary.append_text(amount_text(money, value))
        total.update(summary)

    def selected(self) -> BudgetLine | None:
        """Return the budget line under the cursor."""
        key = self.query_one(ListTable).selected_key()
        return next((b for b in self.lines if str(b.budget.id) == key), None)

    def on_data_table_row_selected(self, message: ListTable.RowSelected) -> None:
        """Edit the budget picked with `enter`."""
        message.stop()
        self.action_edit()

    def action_period(self, step: int) -> None:
        """Show the previous or next period."""
        period = self.period
        if period is None:
            return
        index = self.periods.index(period) + step
        if 0 <= index < len(self.periods):
            self.period_id = self.periods[index].id
            self.query_one(ListTable).clear()
            self.reload()

    def _form(self, line: BudgetLine | None) -> None:
        period = self.period
        if period is None:
            self.notify("Create a period first: press 4, then n.", severity="warning")
            return
        categories = self.book.categories.list()
        if not categories:
            self.notify("Create a category first: press 3, then n.", severity="warning")
            return
        by_id = {c.id: c for c in categories}
        options = [(category_label(c.id, by_id), c.id) for c in categories]
        money = self.money

        def submit(values: FormValues) -> bool:
            save_budget(
                self.book,
                money,
                category_id=values["category"],
                period_id=period.id,
                amount=values["amount"],
                budget_id=line.budget.id if line else None,
            )
            return True

        self.app.push_screen(
            FormScreen(
                f"Budget for {period.name}",
                [
                    ChoiceField(
                        "category",
                        "Category",
                        options,
                        line.category.id if line else categories[0].id,
                    ),
                    TextField(
                        "amount",
                        "Amount",
                        money.plain(line.budget.amount) if line else "",
                        "allowance, e.g. 300",
                    ),
                ],
                submit,
                help="A budget on a top-level category also covers its subcategories.",
            )
        )

    def action_new(self) -> None:
        """Add a budget to the period."""
        self._form(None)

    def action_edit(self) -> None:
        """Edit the selected budget."""
        line = self.selected()
        if line is not None:
            self._form(line)

    def action_delete(self) -> None:
        """Delete the selected budget."""
        line = self.selected()
        if line is None:
            return

        def confirmed(answer: bool | None) -> None:
            if answer and self.attempt(
                lambda: self.book.budgets.delete(line.budget.id)
            ):
                self.reload()

        self.app.push_screen(
            ConfirmScreen(f"Delete the budget for “{line.category.name}”?"), confirmed
        )

    def action_copy(self) -> None:
        """Copy every budget of another period into this one."""
        period = self.period
        others = [p for p in self.periods if period and p.id != period.id]
        if period is None or not others:
            self.notify("There is no other period to copy from.")
            return
        index = self.periods.index(period)
        default = self.periods[index - 1] if index > 0 else others[0]

        def submit(values: FormValues) -> bool:
            self.book.budgets.copy(
                values["source"], period.id, overwrite=values["overwrite"] == "yes"
            )
            return True

        self.app.push_screen(
            FormScreen(
                f"Copy budgets into {period.name}",
                [
                    ChoiceField(
                        "source",
                        "From period",
                        [(f"{p.name} ({period_range(p)})", p.id) for p in others],
                        default.id,
                    ),
                    ChoiceField(
                        "overwrite",
                        "Existing budgets",
                        [("Keep", "no"), ("Overwrite", "yes")],
                        "no",
                    ),
                ],
                submit,
                save_label="Copy",
            )
        )
