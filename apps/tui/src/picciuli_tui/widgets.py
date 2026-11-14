"""Reusable widgets: the month calendar and the list table used by every screen."""

from __future__ import annotations

import datetime as dt
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Tab, Tabs
from textual.widgets.data_table import RowDoesNotExist

from picciuli import Period
from picciuli_tui.calendar_model import WEEKS, DayFlow, month_grid, shift_month
from picciuli_tui.formatting import MoneyFormat

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def amount_text(
    money: MoneyFormat, value: int, *, plus: bool = False, bold: bool = False
) -> Text:
    """Return a right-aligned amount, green when positive and red when negative."""
    color = "green" if value > 0 else "red" if value < 0 else ""
    style = f"{color} bold".strip() if bold else color
    return Text(money.amount(value, plus=plus), style=style, justify="right")


SCREEN_TABS = (
    ("overview", "1 Overview"),
    ("accounts", "2 Accounts"),
    ("categories", "3 Categories"),
    ("periods", "4 Periods"),
    ("budgets", "5 Budgets"),
)
"""Application modes in tab order, with their labels (including the hotkey)."""


class ScreenTabs(Tabs, can_focus=False):
    """The row of screen tabs at the top of every main screen.

    It never takes the focus, so arrow keys keep working in the screen below.
    Activating a tab posts `Tabs.TabActivated` with the mode name as tab id.
    """

    def __init__(self, active: str) -> None:
        super().__init__(
            *(Tab(label, id=mode) for mode, label in SCREEN_TABS), active=active
        )


class ListTable(DataTable[object]):
    """A row-cursor table with `j`/`k` navigation, keyed by entity identifiers."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, cursor_type="row", zebra_stripes=True)

    def selected_key(self) -> str | None:
        """Return the key of the row under the cursor, if any."""
        if not self.row_count:
            return None
        row_key, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
        return row_key.value

    def select_key(self, key: str | None) -> None:
        """Move the cursor to the row with `key`, if it exists."""
        if key is None:
            return
        try:
            index = self.get_row_index(key)
        except RowDoesNotExist:
            return
        self.move_cursor(row=index)


def _box_drawing_table() -> dict[tuple[int, int, int, int], str]:
    """Map arm weights (up, down, left, right) to box-drawing characters.

    A weight is 0 (no line), 1 (light) or 2 (heavy). The table is derived from
    the Unicode character names, e.g. "BOX DRAWINGS DOWN LIGHT AND RIGHT HEAVY".
    """
    directions = {
        "UP": ("up",),
        "DOWN": ("down",),
        "LEFT": ("left",),
        "RIGHT": ("right",),
        "VERTICAL": ("up", "down"),
        "HORIZONTAL": ("left", "right"),
    }
    weights = {"LIGHT": 1, "HEAVY": 2}
    skipped = {"DOUBLE", "SINGLE", "DASH", "ARC", "DIAGONAL", "TRIPLE", "QUADRUPLE"}
    table = {(0, 0, 0, 0): " "}
    for code in range(0x2500, 0x2580):
        name = unicodedata.name(chr(code)).removeprefix("BOX DRAWINGS ")
        if skipped & set(name.split()):
            continue
        arms = dict.fromkeys(("up", "down", "left", "right"), 0)
        weight = 0
        # A part without its own weight inherits the previous one:
        # "LIGHT DOWN AND RIGHT" is light in both directions.
        for part in name.split(" AND "):
            words = part.split()
            weight = next((weights[w] for w in words if w in weights), weight)
            for word in words:
                for direction in directions.get(word, ()):
                    arms[direction] = weight
        table[(arms["up"], arms["down"], arms["left"], arms["right"])] = chr(code)
    return table


BOX = _box_drawing_table()


@dataclass(frozen=True)
class CalendarGeometry:
    """Where the calendar draws things, in widget coordinates.

    Lines: 0 title, 1 weekday names, 2 top border, then each week has
    `cell_height` content lines followed by a border line.
    """

    pad: int
    cell_width: int
    cell_height: int

    TOP = 3

    @property
    def width(self) -> int:
        """Width of the grid including its borders."""
        return self.cell_width * 7 + 8

    @property
    def height(self) -> int:
        """Height of the whole calendar."""
        return self.TOP + WEEKS * (self.cell_height + 1)

    def cell_at(self, x: int, y: int) -> tuple[int, int] | None:
        """Return the (week, weekday) of the cell at a point, or `None`."""
        gx, gy = x - self.pad - 1, y - self.TOP
        if gx < 0 or gy < 0:
            return None
        week, line = divmod(gy, self.cell_height + 1)
        column, offset = divmod(gx, self.cell_width + 1)
        if line == self.cell_height or offset == self.cell_width:
            return None  # on a border
        if week >= WEEKS or column >= 7:
            return None
        return week, column

    def cell_origin(self, week: int, column: int) -> tuple[int, int]:
        """Return the top-left content point of a cell."""
        return (
            self.pad + 1 + column * (self.cell_width + 1),
            self.TOP + week * (self.cell_height + 1),
        )


class CalendarWidget(Widget, can_focus=True):
    """A Monday-first month grid showing each day's net flow.

    Days are boxed cells; the selected day has a heavy accent border. The widget
    only displays what it is given through `show`; moving the selection posts a
    `DayRequested` message, and the owner decides what to do.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "move(-1)", "Day", show=False),
        Binding("right", "move(1)", "Day", show=False),
        Binding("up", "move(-7)", "Week", show=False),
        Binding("down", "move(7)", "Week", show=False),
        Binding("pageup", "month(-1)", "Month", show=False),
        Binding("pagedown", "month(1)", "Month", show=False),
    ]

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "calendar--title",
        "calendar--weekday",
        "calendar--weekend",
        "calendar--grid",
        "calendar--selected-border",
        "calendar--other-month",
        "calendar--today",
        "calendar--band",
        "calendar--band-edge",
        "calendar--selected",
        "calendar--income",
        "calendar--expense",
        "calendar--transfer",
    }

    DEFAULT_CSS = """
    CalendarWidget {
        height: 1fr;
        min-height: 21;
        width: 1fr;
        min-width: 29;
        & > .calendar--title { text-style: bold; color: $text; }
        & > .calendar--weekday { text-style: bold; color: $text-muted; }
        & > .calendar--weekend { color: $text-muted; }
        & > .calendar--grid { color: $foreground 25%; }
        & > .calendar--selected-border { color: $accent; text-style: bold; }
        & > .calendar--other-month { color: $text-disabled; }
        & > .calendar--today { text-style: bold reverse; color: $warning; }
        & > .calendar--band { background: $primary 18%; }
        & > .calendar--band-edge { background: $primary 36%; }
        & > .calendar--selected {
            background: $accent 35%;
            text-style: bold;
        }
        &:focus > .calendar--selected {
            background: $accent 70%;
            color: $text;
        }
        & > .calendar--income { color: $success; }
        & > .calendar--expense { color: $error; }
        & > .calendar--transfer { color: $text-muted; }
    }
    """

    MIN_CELL = 3
    MAX_CELL = 16
    MIN_LINES = 2
    MAX_LINES = 4
    FLOW_MIN_CELL = 6

    class DayRequested(Message):
        """The user asked to select another day."""

        def __init__(self, day: dt.date) -> None:
            super().__init__()
            self.day = day

    def __init__(
        self, day: dt.date, *, money: MoneyFormat, id: str | None = None
    ) -> None:
        super().__init__(id=id)
        self.day = day
        self.today = day
        self.money = money
        self.flows: Mapping[dt.date, DayFlow] = {}
        self.band: Period | None = None

    def show(
        self,
        day: dt.date,
        *,
        today: dt.date,
        flows: Mapping[dt.date, DayFlow],
        band: Period | None,
        money: MoneyFormat,
    ) -> None:
        """Display `day` selected, with the given flows and period band."""
        self.day, self.today, self.flows, self.band = day, today, flows, band
        self.money = money
        self.refresh()

    # Actions and events

    def action_move(self, days: int) -> None:
        """Request the day `days` away from the selected one."""
        self.post_message(self.DayRequested(self.day + dt.timedelta(days=days)))

    def action_month(self, months: int) -> None:
        """Request the same day `months` away."""
        self.post_message(self.DayRequested(shift_month(self.day, months)))

    def day_at(self, x: int, y: int) -> dt.date | None:
        """Return the day drawn at a point of the widget, if any."""
        cell = self.geometry().cell_at(x, y)
        if cell is None:
            return None
        week, column = cell
        return month_grid(self.day.year, self.day.month)[week][column]

    def on_click(self, event: events.Click) -> None:
        """Select the clicked day, or change month with the title arrows."""
        geometry = self.geometry()
        if event.y == 0:
            x = event.x - geometry.pad
            if 0 <= x < 2:
                self.action_month(-1)
            elif geometry.width - 2 <= x < geometry.width:
                self.action_month(1)
            return
        day = self.day_at(event.x, event.y)
        if day is not None:
            self.post_message(self.DayRequested(day))

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        """Show the previous month."""
        event.stop()
        self.action_month(-1)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        """Show the next month."""
        event.stop()
        self.action_month(1)

    def on_focus(self) -> None:
        """Repaint the selection in its focused style."""
        self.refresh()

    def on_blur(self) -> None:
        """Repaint the selection in its blurred style."""
        self.refresh()

    # Rendering

    def geometry(self) -> CalendarGeometry:
        """Size the cells to fill the widget, within readable limits."""
        width, height = self.size
        cell = min(max((width - 8) // 7, self.MIN_CELL), self.MAX_CELL)
        lines = min(
            max((height - CalendarGeometry.TOP - WEEKS) // WEEKS, self.MIN_LINES),
            self.MAX_LINES,
        )
        pad = max((width - (cell * 7 + 8)) // 2, 0)
        return CalendarGeometry(pad, cell, lines)

    def _style(self, *names: str) -> Style:
        style = Style()
        for name in names:
            style += self.get_component_rich_style(name, partial=True)
        return style

    def _flow_text(self, day: dt.date, cell: int) -> tuple[str, str]:
        flow = self.flows.get(day)
        if flow is None or not flow.count:
            return "", ""
        if cell < self.FLOW_MIN_CELL:
            return "•", "calendar--transfer"
        if flow.transfers_only:
            return "↔", "calendar--transfer"
        if flow.net == 0:
            return "±0", "calendar--transfer"
        kind = "calendar--income" if flow.net > 0 else "calendar--expense"
        return self.money.compact(flow.net), kind

    def _cell_layers(self, day: dt.date) -> list[str]:
        layers: list[str] = []
        if self.band is not None and self.band.contains(day):
            edge = day in (self.band.start, self.band.end)
            layers.append("calendar--band-edge" if edge else "calendar--band")
        if day == self.day:
            layers.append("calendar--selected")
        return layers

    def _cell_lines(self, day: dt.date, geometry: CalendarGeometry) -> list[Text]:
        width = geometry.cell_width
        layers = self._cell_layers(day)
        background = self._style(*layers)
        number_layers = []
        if day.weekday() >= 5:
            number_layers.append("calendar--weekend")
        if day.month != self.day.month:
            number_layers.append("calendar--other-month")
        if day == self.today:
            number_layers.append("calendar--today")
        number = Text(" ", background, end="")
        number.append(f"{day.day:>2}", self._style(*number_layers, *layers))
        number.append(" " * (width - 3), background)
        flow, kind = self._flow_text(day, width)
        flow_style = self._style(kind, *layers) if kind else background
        if width < self.FLOW_MIN_CELL:
            flow_line = Text(flow.center(width), flow_style, end="")
        else:
            flow_line = Text(flow.rjust(width - 1), flow_style, end="")
            flow_line.append(" ", background)
        blank = Text(" " * width, background, end="")
        return [number] + [blank] * (geometry.cell_height - 2) + [flow_line]

    def render(self) -> Text:
        """Draw the title, the weekday names and six weeks of boxed cells."""
        geometry = self.geometry()
        cell = geometry.cell_width
        grid = month_grid(self.day.year, self.day.month)
        selected_week, selected_column = next(
            (week, column)
            for week, days in enumerate(grid)
            for column, day in enumerate(days)
            if day == self.day
        )

        def horizontal(row: int, column: int) -> int:
            heavy = column == selected_column and row in (
                selected_week,
                selected_week + 1,
            )
            return 2 if heavy else 1

        def vertical(row: int, column: int) -> int:
            heavy = row == selected_week and column in (
                selected_column,
                selected_column + 1,
            )
            return 2 if heavy else 1

        grid_style = self._style("calendar--grid")
        accent = self._style("calendar--selected-border")

        def line_style(weight: int) -> Style:
            return accent if weight == 2 else grid_style

        pad = " " * geometry.pad
        text = Text(no_wrap=True, overflow="crop", end="")
        title_style = self._style("calendar--title")
        text.append(pad)
        text.append("‹", title_style)
        text.append(f"{self.day:%B %Y}".center(geometry.width - 2), title_style)
        text.append("›\n", title_style)
        text.append(pad + " ")
        names = WEEKDAYS if cell >= 5 else tuple(name[:2] for name in WEEKDAYS)
        for index, name in enumerate(names):
            extra = "calendar--weekend" if index >= 5 else "calendar--weekday"
            text.append(name.center(cell), self._style("calendar--weekday", extra))
            text.append(" ")
        for row in range(WEEKS + 1):
            text.append("\n" + pad)
            for column in range(8):
                arms = (
                    vertical(row - 1, column) if row > 0 else 0,
                    vertical(row, column) if row < WEEKS else 0,
                    horizontal(row, column - 1) if column > 0 else 0,
                    horizontal(row, column) if column < 7 else 0,
                )
                text.append(BOX[arms], line_style(max(arms)))
                if column < 7:
                    weight = horizontal(row, column)
                    text.append(BOX[(0, 0, weight, weight)] * cell, line_style(weight))
            if row == WEEKS:
                break
            cells = [self._cell_lines(day, geometry) for day in grid[row]]
            for line in range(geometry.cell_height):
                text.append("\n" + pad)
                for column in range(8):
                    weight = vertical(row, column)
                    text.append(BOX[(weight, weight, 0, 0)], line_style(weight))
                    if column < 7:
                        text.append_text(cells[column][line])
        return text
