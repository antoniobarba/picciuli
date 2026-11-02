import argparse
import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from blessed import Terminal
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from data import (
    CashFlowRecord,
    CategoryRecord,
    Data,
    PeriodBalanceReport,
    PeriodRecord,
)


PERIOD_COLORS = ("blue", "green", "magenta", "cyan", "yellow", "red")


def month_grid(year: int, month: int) -> list[list[date | None]]:
    weeks = calendar.Calendar(firstweekday=calendar.MONDAY).monthdayscalendar(
        year, month
    )
    return [
        [date(year, month, day) if day else None for day in week]
        for week in weeks
    ]


def shift_month(day: date, months: int) -> date:
    month_index = day.year * 12 + day.month - 1 + months
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    day_number = min(day.day, calendar.monthrange(year, month)[1])
    return date(year, month, day_number)


def parse_amount(value: str) -> int:
    try:
        amount = Decimal(value.strip())
    except InvalidOperation as error:
        raise ValueError("enter a valid amount, such as 12.34") from error
    if not amount.is_finite():
        raise ValueError("amount must be a finite number")
    minor_units = amount * 100
    if minor_units != minor_units.to_integral_value():
        raise ValueError("amount can have at most two decimal places")
    return int(minor_units)


def format_amount(amount: int, currency: str = "$") -> str:
    separator = " " if currency[-1:].isalnum() else ""
    sign = "-" if amount < 0 else ""
    return f"{sign}{currency}{separator}{Decimal(abs(amount)) / 100:,.2f}"


def _key_binding_footer(
    term: Terminal,
    groups: Sequence[Sequence[tuple[str, str]]],
) -> list[str]:
    return [
        "-" * min(term.width, 80),
        *[
            " - ".join(
                f"{term.yellow(key)} {description}"
                for key, description in group
            )
            for group in groups
        ],
    ]


def _periods_for_day(
    day: date,
    periods: Sequence[PeriodRecord],
) -> list[PeriodRecord]:
    return [
        period
        for period in periods
        if (
            period["start_date"].date() <= day
            and (
                period["end_date"] is None
                or period["end_date"].date() >= day
            )
        )
    ]


def _period_for_day(day: date, periods: Sequence[PeriodRecord]) -> PeriodRecord | None:
    matching = _periods_for_day(day, periods)
    return matching[-1] if matching else None


def _calendar_lines(
    term: Terminal,
    selected_day: date,
    periods: Sequence[PeriodRecord],
) -> list[str]:
    lines = [
        term.bold(term.center(selected_day.strftime("%B %Y"), 30)),
        " Mo  Tu  We  Th  Fr  Sa  Su ",
    ]
    for week in month_grid(selected_day.year, selected_day.month):
        cells = []
        for day in week:
            if day is None:
                cells.append("    ")
                continue
            period = _period_for_day(day, periods)
            if day == selected_day:
                style = term.reverse
            elif period is not None:
                color_index = (period["id"] - 1) % len(PERIOD_COLORS)
                style = getattr(term, f"on_{PERIOD_COLORS[color_index]}")
            else:
                style = ""
            cells.append(f"{style}{day.day:>3}{term.normal} ")
        lines.append("".join(cells).rstrip())
    lines.append("")

    month_periods = [
        period
        for period in periods
        if period["start_date"].date().replace(day=1)
        <= date(selected_day.year, selected_day.month, 1)
        and (
            period["end_date"] is None
            or period["end_date"].date()
            >= date(selected_day.year, selected_day.month, 1)
        )
    ]
    for period in month_periods:
        color_index = (period["id"] - 1) % len(PERIOD_COLORS)
        style = getattr(term, f"on_{PERIOD_COLORS[color_index]}")
        lines.append(f"{style}   {term.normal} {period['name']}")
    return lines


def _cash_flow_lines(
    term: Terminal,
    cash_flows: Sequence[CashFlowRecord],
    categories: Sequence[CategoryRecord],
    currency: str,
    width: int,
    selected_cash_flow_id: int | None,
) -> list[str]:
    lines: list[str] = []
    category_symbols = {
        category["id"]: category["symbol"] for category in categories
    }
    if not cash_flows:
        return ["No cash flows for this day."]

    content_width = max(12, width)
    for cash_flow in cash_flows:
        amount = format_amount(cash_flow["amount"], currency)
        if cash_flow["amount"] < 0:
            amount = term.red(amount)
        symbol = category_symbols.get(cash_flow["category_id"], "?")
        description = cash_flow["description"] or "(no description)"
        prefix = ">" if cash_flow["id"] == selected_cash_flow_id else " "
        line = f"{prefix} [{symbol}] {amount} - {description}"
        if term.length(line) > content_width:
            line = line[: max(0, content_width - 1)] + "…"
        lines.append(line)
    return lines


def render_screen(
    term: Terminal,
    selected_day: date,
    periods: Sequence[PeriodRecord],
    report: PeriodBalanceReport | None,
    cash_flows: Sequence[CashFlowRecord] = (),
    categories: Sequence[CategoryRecord] = (),
    currency: str = "$",
    notice: str = "",
    selected_cash_flow_id: int | None = None,
) -> str:
    left_width = 30
    title = term.bold(f"Picciuli - Personal Finance ({currency})")
    calendar_panel = _calendar_lines(term, selected_day, periods)
    cash_width = max(12, (term.width - left_width - 6) // 2)
    balance_width = max(12, term.width - left_width - cash_width - 6)
    cash_panel = _cash_flow_lines(
        term,
        cash_flows,
        categories,
        currency,
        cash_width,
        selected_cash_flow_id,
    )
    balance_panel: list[str] = []

    covering_periods = _periods_for_day(selected_day, periods)
    selected_period_id = report["period"]["id"] if report is not None else None
    selected_period = next(
        (
            period
            for period in covering_periods
            if period["id"] == selected_period_id
        ),
        covering_periods[-1] if covering_periods else None,
    )
    if selected_period is None:
        balance_panel.extend(
            [
                term.bold("No period covers this day."),
                f"Press {term.yellow('[n]')} to start a period here.",
            ]
        )
    else:
        end_label = (
            selected_period["end_date"].strftime("%d %b %Y")
            if selected_period["end_date"] is not None
            else "Open"
        )
        balance_panel.extend(
            [
                term.bold(
                    "Period: "
                    f"{term.yellow('<')}{selected_period['name']} "
                    f"({covering_periods.index(selected_period) + 1}/"
                    f"{len(covering_periods)}){term.yellow('>')}"
                ),
                f"{selected_period['start_date']:%d %b %Y} - {end_label}",
                "",
            ]
        )
        if report is None:
            balance_panel.append("No balance data available.")
        else:
            report_categories = report["categories"]
            if not report_categories:
                balance_panel.append(
                    f"No categories yet. Press {term.yellow('[c]')} to add one."
                )
            else:
                has_root_category = False
                for item in report_categories:
                    if item["parent_id"] is None:
                        if has_root_category:
                            balance_panel.append("")
                        has_root_category = True
                    name = (
                        f"  └─ {item['category_name']}"
                        if item["parent_id"] is not None
                        else item["category_name"]
                    )
                    amount = format_amount(item["balance"], currency)
                    if item["balance"] < 0:
                        amount = term.red(amount)
                    amount_padding = max(0, 16 - term.length(amount))
                    balance_panel.append(
                        f"{name:<22} {' ' * amount_padding}{amount}"
                    )
            total = format_amount(report["total"], currency)
            if report["total"] < 0:
                total = term.red(total)
            total_padding = max(0, 16 - term.length(total))
            balance_panel.extend(
                [
                    "-" * min(balance_width, 32),
                    f"{'Total':<22} {' ' * total_padding}{total}",
                ]
            )

    lines = [term.center(title), "", f"Selected day: {selected_day:%A, %d %B %Y}", ""]
    if term.width >= 100:
        columns = (
            (calendar_panel, left_width),
            (cash_panel, cash_width),
            (balance_panel, balance_width),
        )
        lines.append(
            f"{'Calendar':<{left_width}} │ "
            f"{'Cash flows':<{cash_width}} │ Period balances"
        )
        row_count = max(len(panel) for panel, _ in columns)
        for index in range(row_count):
            cells = []
            for column_index, (panel, width) in enumerate(columns):
                cell = panel[index] if index < len(panel) else ""
                cells.append(cell)
                if column_index < len(columns) - 1:
                    cells.append(" " * max(0, width - term.length(cell)))
                    cells.append(" │ ")
            lines.append("".join(cells))
    else:
        for heading, panel in (
            ("Calendar", calendar_panel),
            ("Cash flows", cash_panel),
            ("Period balances", balance_panel),
        ):
            lines.append(term.bold(heading))
            lines.extend(panel)
            lines.append("")

    if notice:
        lines.append("")
        lines.append(term.bold(notice))
    lines.append("")
    lines.extend(
        _key_binding_footer(
            term,
            [
                [("[←/→]", "day"), ("[↑/↓]", "week"), ("[/]", "month")],
                [("[n]", "new period"), ("[r]", "rename period"), ("[a]", "add cash flow")],
                [("[j/k]", "select item"), ("[e]", "edit item"), ("[d]", "delete item")],
                [
                    ("[c]", "category"),
                    ("[m]", "manage categories"),
                    ("[p]", "manage periods"),
                    ("[<]", "previous period"),
                    ("[>]", "next period"),
                    ("[u]", "currency"),
                    ("[q]", "quit"),
                ],
            ],
        )
    )
    return term.home + term.clear + "\n".join(lines)


def _read_line(
    term: Terminal,
    prompt: str,
    default: str | None = None,
    prelude: str = "",
) -> str | None:
    value = ""
    while True:
        shown = value if value else (default or "")
        display_prompt = prompt.replace("Esc", term.yellow("Esc"))
        print(
            term.home + term.clear + prelude + display_prompt + shown,
            end="",
            flush=True,
        )
        key = term.inkey()
        if key.name == "KEY_ESCAPE" or key == "\x1b":
            return None
        if key.name in ("KEY_ENTER", "KEY_RETURN") or key in ("\r", "\n"):
            return value or default or ""
        if key.name == "KEY_BACKSPACE" or key in ("\b", "\x7f"):
            value = value[:-1]
        elif not key.is_sequence and key.isprintable():
            value += str(key)


def _add_category(
    term: Terminal,
    data: Data,
    *,
    choose_parent: bool = True,
) -> str:
    name = _read_line(term, "New category name (Esc cancels): ")
    if name is None:
        return "Category creation cancelled."
    parent_id = None
    roots = [
        category
        for category in data.list_categories()
        if category["parent_id"] is None
    ]
    if choose_parent and roots:
        options = "\n".join(
            f"{index}. {category['name']}"
            for index, category in enumerate(roots, start=1)
        )
        parent_choice = _read_line(
            term,
            "Parent number (0 for top-level): ",
            prelude=f"Choose a parent category or 0 for top-level:\n{options}\n",
        )
        if parent_choice is None:
            return "Category creation cancelled."
        try:
            selected = int(parent_choice)
            if selected < 0 or selected > len(roots):
                raise ValueError
            if selected:
                parent_id = roots[selected - 1]["id"]
        except ValueError:
            raise ValueError("choose a valid parent category number") from None
    default_symbol = "".join(part[0] for part in name.split())[:4].upper()
    symbol = _read_line(term, f"Category symbol [{default_symbol}]: ", default_symbol)
    if symbol is None:
        return "Category creation cancelled."
    category = data.create_category(name, parent_id, symbol)
    return f"Created category: [{category['symbol']}] {category['name']}."


def _manage_categories(term: Terminal, data: Data) -> str:
    categories = data.list_categories()
    selected_id: int | None = categories[0]["id"] if categories else None
    notice = ""

    while True:
        categories = data.list_categories()
        selected_index = next(
            (
                index
                for index, category in enumerate(categories)
                if category["id"] == selected_id
            ),
            0,
        )
        selected = categories[selected_index] if categories else None
        if selected is not None:
            selected_id = selected["id"]
        rows = (
            [
                f"{'>' if category['id'] == selected_id else ' '} "
                + (
                    f"└─ [{category['symbol']}] {category['name']}"
                    if category["parent_id"] is not None
                    else f"[{category['symbol']}] {category['name']}"
                )
                for category in categories
            ]
            if categories
            else [f"No categories yet. Press {term.yellow('[c]')} to add one."]
        )
        header = [
            term.bold("Manage categories"),
            "",
        ]
        footer = _key_binding_footer(
            term,
            [
                [("[↑/↓]", "select"), ("[e]", "edit"), ("[d]", "delete")],
                [("[s]", "add subcategory"), ("[c]", "add category")],
                [("[j/k]", "reorder"), ("[Esc/q]", "return to overview")],
            ],
        )
        visible_rows = max(1, term.height - len(header) - len(footer) - 2)
        first_row = min(
            max(0, selected_index - visible_rows + 1),
            max(0, len(rows) - visible_rows),
        )
        lines = header + rows[first_row : first_row + visible_rows]
        if notice:
            lines.extend(["", term.bold(notice)])
        lines.extend(["", *footer])
        print(term.home + term.clear + "\n".join(lines), end="", flush=True)

        key = term.inkey()
        if key.name == "KEY_ESCAPE" or key == "\x1b" or key.lower() == "q":
            return notice or "Category management closed."
        if key.lower() == "c":
            try:
                notice = _add_category(term, data, choose_parent=False)
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not create category: {error}"
            continue
        if selected is None:
            continue
        if key.name == "KEY_UP":
            selected_id = categories[max(0, selected_index - 1)]["id"]
            notice = ""
            continue
        if key.name == "KEY_DOWN":
            selected_id = categories[min(len(categories) - 1, selected_index + 1)][
                "id"
            ]
            notice = ""
            continue
        if key.lower() in ("j", "k"):
            siblings = [
                category
                for category in categories
                if category["parent_id"] == selected["parent_id"]
            ]
            sibling_index = next(
                index
                for index, category in enumerate(siblings)
                if category["id"] == selected_id
            )
            offset = 1 if key.lower() == "j" else -1
            target_index = sibling_index + offset
            if not 0 <= target_index < len(siblings):
                notice = "Category is already at the end of its sibling group."
                continue
            try:
                data.update_category(
                    selected_id,
                    selected["name"],
                    selected["parent_id"],
                    selected["symbol"],
                    target_index + 1,
                )
                notice = ""
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not reorder category: {error}"
            continue
        if key.lower() == "e":
            try:
                notice = _edit_category(term, data, selected, categories)
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not edit category: {error}"
            continue
        if key.lower() == "d":
            confirmation = _read_line(
                term,
                f"Type {term.yellow('[y]')} to confirm deletion (anything else cancels): ",
                prelude=f"Delete [{selected['symbol']}] {selected['name']}?\n",
            )
            if confirmation is None or confirmation.lower() != "y":
                notice = "Category deletion cancelled."
                continue
            try:
                data.delete_category(selected_id)
                categories.pop(selected_index)
                selected_id = (
                    categories[min(selected_index, len(categories) - 1)]["id"]
                    if categories
                    else 0
                )
                notice = f"Deleted category {selected['name']}."
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not delete category: {error}"
            continue
        if key.lower() == "s":
            if selected["parent_id"] is not None:
                notice = "Subcategories cannot have their own subcategories."
                continue
            name = _read_line(term, "New subcategory name (Esc cancels): ")
            if name is None:
                notice = "Subcategory creation cancelled."
                continue
            default_symbol = "".join(part[0] for part in name.split())[:4].upper()
            symbol = _read_line(
                term, f"Category symbol [{default_symbol}]: ", default_symbol
            )
            if symbol is None:
                notice = "Subcategory creation cancelled."
                continue
            try:
                created = data.create_category(name, selected_id, symbol)
                selected_id = created["id"]
                notice = f"Created subcategory [{created['symbol']}] {created['name']}."
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not create subcategory: {error}"
            continue
def _edit_category(
    term: Terminal,
    data: Data,
    category: CategoryRecord,
    categories: Sequence[CategoryRecord],
) -> str:
    name = _read_line(term, "Name: ", category["name"])
    if name is None:
        return "Category edit cancelled."
    symbol = _read_line(term, "Symbol: ", category["symbol"])
    if symbol is None:
        return "Category edit cancelled."

    parent_id = category["parent_id"]
    has_children = any(item["parent_id"] == category["id"] for item in categories)
    if not has_children:
        roots = [
            item
            for item in categories
            if item["parent_id"] is None and item["id"] != category["id"]
        ]
        current_parent_number = next(
            (
                index
                for index, item in enumerate(roots, start=1)
                if item["id"] == parent_id
            ),
            0,
        )
        parent_options = "\n".join(
            f"{index}. [{item['symbol']}] {item['name']}"
            for index, item in enumerate(roots, start=1)
        )
        parent_choice = _read_line(
            term,
            "Parent number (0 for top-level): ",
            str(current_parent_number),
            prelude=f"Choose a parent or 0 for top-level:\n{parent_options}\n",
        )
        if parent_choice is None:
            return "Category edit cancelled."
        try:
            parent_number = int(parent_choice)
            if parent_number < 0 or parent_number > len(roots):
                raise ValueError
        except ValueError:
            raise ValueError("choose a valid parent category number") from None
        parent_id = roots[parent_number - 1]["id"] if parent_number else None

    updated = data.update_category(
        category["id"], name, parent_id, symbol
    )
    return f"Updated category to [{updated['symbol']}] {updated['name']}."


def _set_currency(term: Terminal, data: Data) -> str:
    currency = _read_line(
        term,
        "Currency symbol/code (Esc cancels): ",
        data.get_currency(),
    )
    if currency is None:
        return "Currency change cancelled."
    return f"Currency set to {data.set_currency(currency)}."


def _add_period(term: Terminal, data: Data, selected_day: date) -> str:
    default_name = selected_day.strftime("%B %Y")
    name = _read_line(
        term,
        f"Period name [{default_name}] (Enter uses default, Esc cancels): ",
        default_name,
    )
    if name is None:
        return "Period creation cancelled."
    period = data.create_period(
        start_date=datetime.combine(selected_day, time.min),
        name=name,
    )
    return f"Created period: {period['name']}."


def _rename_period(term: Terminal, data: Data, period: PeriodRecord | None) -> str:
    if period is None:
        return "Select a day inside a period first."
    name = _read_line(
        term,
        f"New name [{period['name']}] (Enter keeps current, Esc cancels): ",
        period["name"],
    )
    if name is None:
        return "Rename cancelled."
    updated = data.update_period(
        period["id"], period["start_date"], period["end_date"], name
    )
    return f"Renamed period to {updated['name']}."


def _period_date(value: str, field_name: str) -> date:
    if (
        len(value) != 10
        or value[4] != "-"
        or value[7] != "-"
    ):
        raise ValueError(f"{field_name} must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from error


def _period_end_datetime(value: str) -> datetime | None:
    if not value:
        return None
    end_day = _period_date(value, "end date")
    return datetime.combine(end_day, time.max)


def _add_managed_period(term: Terminal, data: Data) -> str:
    today = date.today()
    start_text = _read_line(
        term, "Start date (YYYY-MM-DD): ", today.isoformat()
    )
    if start_text is None:
        return "Period creation cancelled."
    start_day = _period_date(start_text, "start date")
    end_text = _read_line(
        term, "End date (YYYY-MM-DD, blank for open): "
    )
    if end_text is None:
        return "Period creation cancelled."
    end_date = _period_end_datetime(end_text)
    default_name = start_day.strftime("%B %Y")
    name = _read_line(term, f"Period name [{default_name}]: ", default_name)
    if name is None:
        return "Period creation cancelled."
    period = data.create_period(
        datetime.combine(start_day, time.min),
        end_date,
        name,
    )
    return f"Created period: {period['name']}."


def _edit_managed_period(
    term: Terminal,
    data: Data,
    period: PeriodRecord,
) -> str:
    start_text = _read_line(
        term,
        "Start date (YYYY-MM-DD): ",
        period["start_date"].date().isoformat(),
    )
    if start_text is None:
        return "Period edit cancelled."
    start_day = _period_date(start_text, "start date")

    current_end = (
        period["end_date"].date().isoformat()
        if period["end_date"] is not None
        else ""
    )
    end_text = _read_line(
        term,
        "End date (YYYY-MM-DD, blank for open): ",
        current_end,
    )
    if end_text is None:
        return "Period edit cancelled."
    end_date = _period_end_datetime(end_text)
    name = _read_line(term, "Name: ", period["name"])
    if name is None:
        return "Period edit cancelled."
    updated = data.update_period(
        period["id"],
        datetime.combine(start_day, time.min),
        end_date,
        name,
    )
    return f"Updated period: {updated['name']}."


def _manage_periods(term: Terminal, data: Data) -> str:
    periods = data.list_periods()
    selected_id: int | None = periods[0]["id"] if periods else None
    notice = ""

    while True:
        periods = data.list_periods()
        selected_index = next(
            (
                index
                for index, period in enumerate(periods)
                if period["id"] == selected_id
            ),
            0,
        )
        selected = periods[selected_index] if periods else None
        if selected is not None:
            selected_id = selected["id"]
        rows = (
            [
                f"{'>' if period['id'] == selected_id else ' '} "
                f"{period['start_date']:%Y-%m-%d} - "
                f"{period['end_date'].strftime('%Y-%m-%d') if period['end_date'] else 'Open'} "
                f"| {period['name']}"
                for period in periods
            ]
            if periods
            else ["No periods yet."]
        )
        header = [term.bold("Manage periods"), ""]
        footer = _key_binding_footer(
            term,
            [
                [("[↑/↓]", "select"), ("[a]", "add"), ("[e]", "edit")],
                [("[d]", "delete"), ("[Esc/q]", "return to overview")],
            ],
        )
        visible_rows = max(1, term.height - len(header) - len(footer) - 2)
        first_row = min(
            max(0, selected_index - visible_rows + 1),
            max(0, len(rows) - visible_rows),
        )
        lines = header + rows[first_row : first_row + visible_rows]
        if notice:
            lines.extend(["", term.bold(notice)])
        lines.extend(["", *footer])
        print(term.home + term.clear + "\n".join(lines), end="", flush=True)

        key = term.inkey()
        if key.name == "KEY_ESCAPE" or key == "\x1b" or key.lower() == "q":
            return notice or "Period management closed."
        if key.lower() == "a":
            try:
                notice = _add_managed_period(term, data)
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not create period: {error}"
            continue
        if selected is None:
            continue
        if key.name == "KEY_UP":
            selected_id = periods[max(0, selected_index - 1)]["id"]
            notice = ""
            continue
        if key.name == "KEY_DOWN":
            selected_id = periods[min(len(periods) - 1, selected_index + 1)]["id"]
            notice = ""
            continue
        if key.lower() == "e":
            try:
                notice = _edit_managed_period(term, data, selected)
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not edit period: {error}"
            continue
        if key.lower() == "d":
            confirmation = _read_line(
                term,
                f"Type {term.yellow('[y]')} to confirm deletion (anything else cancels): ",
                prelude=f"Delete period {selected['name']}?\n",
            )
            if confirmation is None or confirmation.lower() != "y":
                notice = "Period deletion cancelled."
                continue
            try:
                data.delete_period(selected["id"])
                periods.pop(selected_index)
                selected_id = (
                    periods[min(selected_index, len(periods) - 1)]["id"]
                    if periods
                    else None
                )
                notice = f"Deleted period {selected['name']}."
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not delete period: {error}"


def _add_cash_flow(
    term: Terminal,
    data: Data,
    selected_day: date,
    categories: Sequence[CategoryRecord],
) -> str:
    if not categories:
        return "Create a category first with c."
    description = _read_line(term, "Description (Esc cancels): ")
    if description is None:
        return "Cash-flow creation cancelled."
    amount_text = _read_line(term, "Amount (+ income, - expense; e.g. 12.34): ")
    if amount_text is None:
        return "Cash-flow creation cancelled."
    amount = parse_amount(amount_text)

    category_options = "\n".join(
        f"{index}. "
        + (
            f"  └─ {category['name']}"
            if category["parent_id"] is not None
            else category["name"]
        )
        for index, category in enumerate(categories, start=1)
    )
    category_text = _read_line(
        term,
        "Category number: ",
        prelude=f"Choose a category (Esc cancels):\n{category_options}\n",
    )
    if category_text is None:
        return "Cash-flow creation cancelled."
    try:
        category_index = int(category_text) - 1
        category_id = categories[category_index]["id"]
    except (ValueError, IndexError):
        raise ValueError("choose a valid category number") from None

    data.create_cash_flow(
        amount=amount,
        category_id=category_id,
        occurred_at=datetime.combine(selected_day, time.min),
        description=description or None,
    )
    return f"Added cash flow: {format_amount(amount, data.get_currency())}."


def _edit_cash_flow(
    term: Terminal,
    data: Data,
    cash_flow: CashFlowRecord,
    categories: Sequence[CategoryRecord],
) -> str:
    description = _read_line(
        term, "Cash-flow name: ", cash_flow["description"] or ""
    )
    if description is None:
        return "Cash-flow edit cancelled."
    amount_default = f"{Decimal(cash_flow['amount']) / 100:.2f}"
    amount_text = _read_line(
        term,
        "Amount (+ income, - expense): ",
        amount_default,
    )
    if amount_text is None:
        return "Cash-flow edit cancelled."
    amount = parse_amount(amount_text)
    options = "\n".join(
        f"{index}. [{category['symbol']}] "
        + (
            f"  └─ {category['name']}"
            if category["parent_id"] is not None
            else category["name"]
        )
        for index, category in enumerate(categories, start=1)
    )
    current_category = next(
        (
            index
            for index, category in enumerate(categories, start=1)
            if category["id"] == cash_flow["category_id"]
        ),
        1,
    )
    category_choice = _read_line(
        term,
        "Category number: ",
        str(current_category),
        prelude=f"Choose a category:\n{options}\n",
    )
    if category_choice is None:
        return "Cash-flow edit cancelled."
    try:
        category_index = int(category_choice) - 1
        category_id = categories[category_index]["id"]
    except (ValueError, IndexError):
        raise ValueError("choose a valid category number") from None
    data.update_cash_flow(
        cash_flow["id"],
        amount,
        category_id,
        cash_flow["occurred_at"],
        description or None,
    )
    return "Cash-flow item updated."


def _delete_cash_flow(term: Terminal, data: Data, cash_flow: CashFlowRecord) -> str:
    description = cash_flow["description"] or "(no name)"
    confirmation = _read_line(
        term,
        f"Type {term.yellow('[y]')} to confirm deletion (anything else cancels): ",
        prelude=f"Delete {description} ({format_amount(cash_flow['amount'], data.get_currency())})?\n",
    )
    if confirmation is None or confirmation.lower() != "y":
        return "Cash-flow deletion cancelled."
    data.delete_cash_flow(cash_flow["id"])
    return f"Deleted cash-flow item {description}."


def run_ui(database_path: Path) -> None:
    term = Terminal()
    data = Data(str(database_path))
    selected_day = date.today()
    selected_cash_flow_id: int | None = None
    selected_period_id: int | None = None
    notice = ""
    try:
        with term.fullscreen(), term.cbreak(), term.hidden_cursor():
            while True:
                periods = data.list_periods()
                categories = data.list_categories()
                day_start = datetime.combine(selected_day, time.min)
                day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
                cash_flows = data.list_cash_flows(
                    start_date=day_start,
                    end_date=day_end,
                )
                available_cash_flow_ids = {
                    cash_flow["id"] for cash_flow in cash_flows
                }
                if selected_cash_flow_id not in available_cash_flow_ids:
                    selected_cash_flow_id = (
                        cash_flows[0]["id"] if cash_flows else None
                    )
                covering_periods = _periods_for_day(selected_day, periods)
                if selected_period_id not in {
                    period["id"] for period in covering_periods
                }:
                    selected_period_id = (
                        covering_periods[-1]["id"] if covering_periods else None
                    )
                selected_period = next(
                    (
                        period
                        for period in covering_periods
                        if period["id"] == selected_period_id
                    ),
                    None,
                )
                report = (
                    data.get_period_balances(selected_period["id"])
                    if selected_period is not None
                    else None
                )
                currency = data.get_currency()
                print(
                    render_screen(
                        term,
                        selected_day,
                        periods,
                        report,
                        cash_flows,
                        categories,
                        currency,
                        notice,
                        selected_cash_flow_id,
                    ),
                    end="",
                    flush=True,
                )
                notice = ""
                key = term.inkey(timeout=0.25)
                if not key:
                    continue
                if key.lower() == "q" or key == "\x03":
                    break
                if key.name == "KEY_LEFT":
                    selected_day -= timedelta(days=1)
                    selected_cash_flow_id = None
                elif key.name == "KEY_RIGHT":
                    selected_day += timedelta(days=1)
                    selected_cash_flow_id = None
                elif key.name == "KEY_UP":
                    selected_day -= timedelta(days=7)
                    selected_cash_flow_id = None
                elif key.name == "KEY_DOWN":
                    selected_day += timedelta(days=7)
                    selected_cash_flow_id = None
                elif key in ("<", ">") and covering_periods:
                    current_index = next(
                        (
                            index
                            for index, period in enumerate(covering_periods)
                            if period["id"] == selected_period_id
                        ),
                        0,
                    )
                    offset = -1 if key == "<" else 1
                    selected_period_id = covering_periods[
                        (current_index + offset) % len(covering_periods)
                    ]["id"]
                elif key == "[":
                    selected_day = shift_month(selected_day, -1)
                    selected_cash_flow_id = None
                elif key == "]":
                    selected_day = shift_month(selected_day, 1)
                    selected_cash_flow_id = None
                elif key.lower() in ("j", "k") and cash_flows:
                    current_index = next(
                        (
                            index
                            for index, cash_flow in enumerate(cash_flows)
                            if cash_flow["id"] == selected_cash_flow_id
                        ),
                        0,
                    )
                    offset = 1 if key.lower() == "j" else -1
                    selected_cash_flow_id = cash_flows[
                        (current_index + offset) % len(cash_flows)
                    ]["id"]
                elif key.lower() in ("e", "d"):
                    selected_cash_flow = next(
                        (
                            cash_flow
                            for cash_flow in cash_flows
                            if cash_flow["id"] == selected_cash_flow_id
                        ),
                        None,
                    )
                    if selected_cash_flow is None:
                        notice = "There is no cash-flow item selected."
                    elif key.lower() == "e":
                        try:
                            notice = _edit_cash_flow(
                                term,
                                data,
                                selected_cash_flow,
                                categories,
                            )
                        except (IntegrityError, LookupError, ValueError) as error:
                            notice = f"Could not edit cash flow: {error}"
                    else:
                        try:
                            notice = _delete_cash_flow(
                                term, data, selected_cash_flow
                            )
                            if notice.startswith("Deleted"):
                                selected_cash_flow_id = None
                        except (IntegrityError, LookupError, ValueError) as error:
                            notice = f"Could not delete cash flow: {error}"
                elif key.lower() == "n":
                    try:
                        notice = _add_period(term, data, selected_day)
                        selected_period_id = None
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not create period: {error}"
                elif key.lower() == "r":
                    try:
                        notice = _rename_period(
                            term, data, _period_for_day(selected_day, periods)
                        )
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not rename period: {error}"
                elif key.lower() == "p":
                    try:
                        notice = _manage_periods(term, data)
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not manage periods: {error}"
                elif key.lower() == "c":
                    try:
                        notice = _add_category(term, data)
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not create category: {error}"
                elif key.lower() == "m":
                    try:
                        notice = _manage_categories(term, data)
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not manage category: {error}"
                elif key.lower() == "a":
                    try:
                        notice = _add_cash_flow(term, data, selected_day, categories)
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not add cash flow: {error}"
                elif key.lower() == "u":
                    try:
                        notice = _set_currency(term, data)
                    except (LookupError, ValueError) as error:
                        notice = f"Could not update currency: {error}"
    finally:
        data.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Personal finance terminal UI")
    parser.add_argument(
        "database",
        type=Path,
        help="SQLite database file to open",
    )
    args = parser.parse_args(argv)
    try:
        run_ui(args.database)
    except (OSError, RuntimeError, SQLAlchemyError, ValueError, LookupError) as error:
        print(f"Error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
