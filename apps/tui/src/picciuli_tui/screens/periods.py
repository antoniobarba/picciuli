"""The list of periods."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Footer, Static

from picciuli import Period
from picciuli_tui.formatting import short_date
from picciuli_tui.forms import default_period_name, save_period
from picciuli_tui.screens.base import BookScreen
from picciuli_tui.screens.modals import (
    ConfirmScreen,
    FormScreen,
    FormValues,
    TextField,
)
from picciuli_tui.widgets import ListTable

PERIOD_HELP = (
    "Leave the end empty for an open-ended period. Creating an open-ended period "
    "ends the earlier open-ended ones the day before it starts."
)


class PeriodsScreen(BookScreen):
    """Every period, oldest first; current periods are marked."""

    SUB_TITLE = "Periods"
    MODE = "periods"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "new", "New"),
        Binding("e", "edit", "Edit"),
        Binding("d,delete", "delete", "Delete"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.periods: list[Period] = []

    def compose(self) -> ComposeResult:
        """Build the table."""
        yield from self.top_bar()
        yield Static(
            "[b]Periods[/] · ● marks the periods covering today", classes="pane-title"
        )
        yield ListTable(id="periods")
        yield Footer()

    def on_mount(self) -> None:
        """Add the columns."""
        table = self.query_one(ListTable)
        for label in ("", "Name", "Start", "End", "Days"):
            table.add_column(label, key=label.lower() or "current")

    def reload(self) -> None:
        """Read the periods."""
        today = self.today()
        self.periods = self.book.periods.list()
        table = self.query_one(ListTable)
        selected = table.selected_key()
        table.clear()
        current_row = None
        for index, period in enumerate(self.periods):
            current = period.contains(today)
            if current:
                current_row = index
            table.add_row(
                Text("●", style="green") if current else "",
                period.name,
                short_date(period.start),
                short_date(period.end) if period.end else "open",
                str((period.end - period.start).days + 1) if period.end else "",
                key=str(period.id),
            )
        if selected is None and current_row is not None:
            table.move_cursor(row=current_row)
        else:
            table.select_key(selected)

    def selected(self) -> Period | None:
        """Return the period under the cursor."""
        key = self.query_one(ListTable).selected_key()
        return next((p for p in self.periods if str(p.id) == key), None)

    def on_data_table_row_selected(self, message: ListTable.RowSelected) -> None:
        """Edit the period picked with `enter`."""
        message.stop()
        self.action_edit()

    def _form(self, period: Period | None) -> None:
        today = self.today()

        def submit(values: FormValues) -> Period:
            return save_period(
                self.book,
                name=values["name"],
                start=values["start"],
                end=values["end"],
                today=today,
                period_id=period.id if period else None,
            )

        start = period.start if period else today
        self.app.push_screen(
            FormScreen(
                f"Edit {period.name}" if period else "New period",
                [
                    TextField(
                        "name",
                        "Name",
                        period.name if period else "",
                        default_period_name(start),
                    ),
                    TextField("start", "Start", start.isoformat()),
                    TextField(
                        "end",
                        "End",
                        period.end.isoformat() if period and period.end else "",
                        "empty = open-ended",
                    ),
                ],
                submit,
                help=PERIOD_HELP,
            )
        )

    def action_new(self) -> None:
        """Create a period starting today."""
        self._form(None)

    def action_edit(self) -> None:
        """Edit the selected period."""
        period = self.selected()
        if period is not None:
            self._form(period)

    def action_delete(self) -> None:
        """Delete the selected period and its budgets."""
        period = self.selected()
        if period is None:
            return

        def confirmed(answer: bool | None) -> None:
            if answer and self.attempt(lambda: self.book.periods.delete(period.id)):
                self.reload()

        self.app.push_screen(
            ConfirmScreen(
                f"Delete period “{period.name}” and its budgets?\n"
                "Transactions are not affected."
            ),
            confirmed,
        )
