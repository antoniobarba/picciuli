import argparse
import calendar
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Collection, Sequence

from blessed import Terminal
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from data import (
    CashFlowRecord,
    CategoryRecord,
    Data,
    BudgetRecord,
    PeriodBalanceReport,
    PeriodBudgetReport,
    PeriodRecord,
)


PERIOD_COLORS = ("green", "magenta", "cyan", "red", "blue")


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
    groups: Sequence[tuple[str, Sequence[tuple[str, str]]]],
) -> list[str]:
    lines = ["-" * min(term.width, 80)]
    for label, bindings in groups:
        prefix = f"{term.bold(label)}: "
        continuation = " " * len(label + ": ")
        line = prefix
        has_binding = False
        for key, description in bindings:
            binding = f"{term.yellow(key)} {description}"
            separator = "  " if has_binding else ""
            if has_binding and term.length(line) + len(separator) + term.length(
                binding
            ) > term.width:
                lines.append(line)
                line = continuation + binding
                has_binding = True
            else:
                line += separator + binding
                has_binding = True
        lines.append(line)
    return lines


def _periods_for_day(
    day: date,
    periods: Sequence[PeriodRecord],
) -> list[PeriodRecord]:
    return sorted(
        (
            period
            for period in periods
            if (
                period["start_date"].date() <= day
                and (
                    period["end_date"] is None
                    or period["end_date"].date() >= day
                )
            )
        ),
        key=lambda period: (period["start_date"], period["id"]),
    )


def _period_for_day(day: date, periods: Sequence[PeriodRecord]) -> PeriodRecord | None:
    matching = _periods_for_day(day, periods)
    return matching[-1] if matching else None


def _calendar_lines(
    term: Terminal,
    selected_day: date,
    periods: Sequence[PeriodRecord],
    cash_flow_days: Collection[date] = (),
) -> list[str]:
    lines = [
        term.bold(term.center(selected_day.strftime("%B %Y"), 30)),
        " Mo  Tu  We  Th  Fr  Sa  Su ",
    ]
    for week in month_grid(selected_day.year, selected_day.month):
        top_cells = []
        bottom_cells = []
        for day in week:
            if day is None:
                top_cells.append("    ")
                bottom_cells.append("    ")
                continue
            day_periods = _periods_for_day(day, periods)
            first_period = day_periods[0] if day_periods else None
            second_period = day_periods[1] if len(day_periods) > 1 else first_period
            day_label = f"{day.day:>3}{'*' if day in cash_flow_days else ' '}"
            for cells, period, label in (
                (top_cells, first_period, day_label),
                (bottom_cells, second_period, "    "),
            ):
                style = ""
                if period is not None:
                    color_index = (period["id"] - 1) % len(PERIOD_COLORS)
                    style = getattr(term, f"on_{PERIOD_COLORS[color_index]}")
                if day == selected_day:
                    style += term.reverse
                cells.append(f"{style}{label}{term.normal}")
        lines.append("".join(top_cells).rstrip())
        lines.append("".join(bottom_cells).rstrip())
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
    if any(
        day.year == selected_day.year and day.month == selected_day.month
        for day in cash_flow_days
    ):
        lines.append("* Cash-flow items")
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
    budget_report: PeriodBudgetReport | None = None,
    cash_flow_days: Collection[date] = (),
) -> str:
    left_width = 30
    title = term.bold(f"Picciuli - Personal Finance ({currency})")
    calendar_panel = _calendar_lines(
        term,
        selected_day,
        periods,
        {
            *cash_flow_days,
            *(cash_flow["occurred_at"].date() for cash_flow in cash_flows),
        },
    )
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
            budget_amounts = {
                item["category_id"]: item["budget"]
                for item in budget_report["categories"]
            } if budget_report is not None else {}
            category_parent_ids = {
                item["category_id"]: item["parent_id"]
                for item in report_categories
            }
            balance_rows: list[tuple[str, str, str]] = []
            if not report_categories:
                balance_panel.append(
                    f"No categories yet. Press {term.yellow('[c]')} to add one."
                )
            else:
                has_root_category = False
                for item in report_categories:
                    if item["parent_id"] is None:
                        if has_root_category:
                            balance_rows.append(("", "", ""))
                        has_root_category = True
                    name = (
                        f"  └─ {item['category_name']}"
                        if item["parent_id"] is not None
                        else item["category_name"]
                    )
                    amount = format_amount(item["balance"], currency)
                    if item["balance"] < 0:
                        amount = term.red(amount)
                    budget_category_ids = [item["category_id"]]
                    if item["parent_id"] is None:
                        budget_category_ids.extend(
                            category_id
                            for category_id, parent_id in category_parent_ids.items()
                            if parent_id == item["category_id"]
                        )
                    allocated_budget = sum(
                        budget_amounts.get(category_id, 0)
                        for category_id in budget_category_ids
                    )
                    has_budget = any(
                        category_id in budget_amounts
                        for category_id in budget_category_ids
                    )
                    if has_budget:
                        remaining_amount = allocated_budget + item["balance"]
                        remaining = format_amount(remaining_amount, currency)
                        if remaining_amount < 0:
                            remaining = term.red(remaining)
                        allocated = format_amount(allocated_budget, currency)
                        budget_text = f"({remaining}/{allocated} left)"
                    else:
                        budget_text = ""
                    balance_rows.append((name, amount, budget_text))
            total = format_amount(report["total"], currency)
            if report["total"] < 0:
                total = term.red(total)
            amount_width = max(
                [term.length(total)]
                + [term.length(amount) for _, amount, _ in balance_rows]
            )
            budget_width = max(
                [0] + [term.length(budget) for _, _, budget in balance_rows]
            )
            name_width = max(22, balance_width - amount_width - budget_width - 2)
            for name, amount, budget in balance_rows:
                if not name and not amount and not budget:
                    balance_panel.append("")
                    continue
                if term.length(name) > name_width:
                    name = name[: max(0, name_width - 1)] + "…"
                name_padding = max(0, name_width - term.length(name))
                amount_padding = max(0, amount_width - term.length(amount))
                budget_padding = max(0, budget_width - term.length(budget))
                balance_panel.append(
                    f"{name}{' ' * name_padding} "
                    f"{' ' * amount_padding}{amount}"
                    f"{' ' * budget_padding}{' ' if budget_width else ''}{budget}"
                )
            balance_panel.extend(
                [
                    "-" * min(balance_width, 32),
                    f"{'Total':<{name_width}} "
                    f"{' ' * max(0, amount_width - term.length(total))}{total}"
                    f"{' ' * (budget_width + (1 if budget_width else 0))}",
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
                (
                    "Navigate",
                    [("[←/→]", "day"), ("[↑/↓]", "week"), ("[ and ]", "month")],
                ),
                (
                    "Cash flows",
                    [
                        ("[a]", "add"),
                        ("[j/k]", "select"),
                        ("[e]", "edit"),
                        ("[d]", "delete"),
                    ],
                ),
                (
                    "Periods",
                    [
                        ("[n]", "new"),
                        ("[r]", "rename"),
                        ("[</>]", "switch overlap"),
                        ("[p]", "manage"),
                    ],
                ),
                (
                    "Categories & budgets",
                    [
                        ("[c]", "add category"),
                        ("[m]", "manage categories"),
                        ("[b]", "budgets"),
                        ("[v]", "report"),
                    ],
                ),
                ("Loans", [("[l]", "manage loans")]),
                ("App", [("[u]", "currency"), ("[q]", "quit")]),
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
                ("Select", [("[↑/↓]", "move cursor")]),
                (
                    "Category",
                    [
                        ("[e]", "edit"),
                        ("[d]", "delete"),
                        ("[c]", "add"),
                        ("[s]", "add subcategory"),
                    ],
                ),
                ("Order", [("[j/k]", "reorder")]),
                ("Return", [("[Esc/q]", "overview")]),
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
                ("Period", [("[↑/↓]", "select"), ("[a]", "add"), ("[e]", "edit")]),
                ("Delete", [("[d]", "delete")]),
                ("Return", [("[Esc/q]", "overview")]),
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


def _choose_budget_reference(
    term: Terminal,
    prompt: str,
    options: Sequence[tuple[int, str]],
    selected_id: int | None = None,
) -> int | None:
    if not options:
        raise ValueError(f"cannot choose {prompt.lower()}: none are available")
    default = next(
        (
            str(index)
            for index, (option_id, _) in enumerate(options, start=1)
            if option_id == selected_id
        ),
        "1",
    )
    labels = "\n".join(
        f"{index}. {label}" for index, (_, label) in enumerate(options, start=1)
    )
    choice = _read_line(
        term,
        f"{prompt} number: ",
        default,
        prelude=f"Choose {prompt.lower()}:\n{labels}\n",
    )
    if choice is None:
        return None
    try:
        index = int(choice) - 1
        return options[index][0]
    except (ValueError, IndexError):
        raise ValueError(f"choose a valid {prompt.lower()} number") from None


def _budget_references(
    data: Data,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    periods = [
        (period["id"], f"{period['name']} ({period['start_date']:%Y-%m-%d})")
        for period in data.list_periods()
    ]
    categories = [
        (
            category["id"],
            (
                f"└─ {category['name']}"
                if category["parent_id"] is not None
                else category["name"]
            ),
        )
        for category in data.list_categories()
    ]
    return periods, categories


def _add_budget(term: Terminal, data: Data) -> tuple[str, int | None]:
    periods, categories = _budget_references(data)
    period_id = _choose_budget_reference(term, "Period", periods)
    if period_id is None:
        return "Budget creation cancelled.", None
    category_id = _choose_budget_reference(term, "Category", categories)
    if category_id is None:
        return "Budget creation cancelled.", None
    amount_text = _read_line(term, "Budget amount (e.g. 123.45): ")
    if amount_text is None:
        return "Budget creation cancelled.", None
    budget = data.create_budget(parse_amount(amount_text), category_id, period_id)
    category_name = dict(categories)[category_id]
    return f"Created budget for {category_name}.", budget["id"]


def _edit_budget(
    term: Terminal,
    data: Data,
    budget: BudgetRecord,
) -> str:
    periods, categories = _budget_references(data)
    period_id = _choose_budget_reference(
        term, "Period", periods, budget["period_id"]
    )
    if period_id is None:
        return "Budget edit cancelled."
    category_id = _choose_budget_reference(
        term, "Category", categories, budget["category_id"]
    )
    if category_id is None:
        return "Budget edit cancelled."
    amount_text = _read_line(
        term,
        "Budget amount: ",
        f"{Decimal(budget['amount']) / 100:.2f}",
    )
    if amount_text is None:
        return "Budget edit cancelled."
    data.update_budget(
        budget["id"],
        parse_amount(amount_text),
        category_id,
        period_id,
    )
    return "Budget updated."


def _manage_budgets(term: Terminal, data: Data) -> str:
    budgets = data.list_budgets()
    selected_id: int | None = budgets[0]["id"] if budgets else None
    notice = ""
    while True:
        budgets = data.list_budgets()
        periods, categories = _budget_references(data)
        period_names = dict(periods)
        category_names = dict(categories)
        selected_index = next(
            (
                index
                for index, budget in enumerate(budgets)
                if budget["id"] == selected_id
            ),
            0,
        )
        selected = budgets[selected_index] if budgets else None
        if selected is not None:
            selected_id = selected["id"]
        rows = (
            [
                f"{'>' if budget['id'] == selected_id else ' '} "
                f"{period_names[budget['period_id']]} / "
                f"{category_names[budget['category_id']]} - "
                f"{format_amount(budget['amount'], data.get_currency())}"
                for budget in budgets
            ]
            if budgets
            else ["No budgets yet."]
        )
        footer = _key_binding_footer(
            term,
            [
                ("Budget", [("[↑/↓]", "select"), ("[a]", "add"), ("[e]", "edit")]),
                ("Delete", [("[d]", "delete")]),
                ("Return", [("[Esc/q]", "overview")]),
            ],
        )
        header = [term.bold("Manage budgets"), ""]
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
            return notice or "Budget management closed."
        if key.lower() == "a":
            try:
                notice, selected_id = _add_budget(term, data)
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not create budget: {error}"
            continue
        if selected is None:
            continue
        if key.name == "KEY_UP":
            selected_id = budgets[max(0, selected_index - 1)]["id"]
            notice = ""
            continue
        if key.name == "KEY_DOWN":
            selected_id = budgets[min(len(budgets) - 1, selected_index + 1)]["id"]
            notice = ""
            continue
        if key.lower() == "e":
            try:
                notice = _edit_budget(term, data, selected)
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not edit budget: {error}"
            continue
        if key.lower() == "d":
            confirmation = _read_line(
                term,
                f"Type {term.yellow('[y]')} to confirm deletion (anything else cancels): ",
                prelude="Delete selected budget?\n",
            )
            if confirmation is None or confirmation.lower() != "y":
                notice = "Budget deletion cancelled."
                continue
            try:
                data.delete_budget(selected["id"])
                budgets.pop(selected_index)
                selected_id = (
                    budgets[min(selected_index, len(budgets) - 1)]["id"]
                    if budgets
                    else None
                )
                notice = "Budget deleted."
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not delete budget: {error}"


def _add_loan(term: Terminal, data: Data) -> tuple[str, int | None]:
    name = _read_line(term, "Loan name (Esc cancels): ")
    if name is None:
        return "Loan creation cancelled.", None
    amount_text = _read_line(term, "Total loan amount (e.g. 1200.00): ")
    if amount_text is None:
        return "Loan creation cancelled.", None
    loan = data.create_loan(name, parse_amount(amount_text))
    return f"Added loan {loan['name']}.", loan["id"]


def _manage_loans(term: Terminal, data: Data) -> str:
    loans = data.list_loans()
    selected_id = loans[0]["id"] if loans else None
    payment_offset = 0
    notice = ""
    while True:
        loans = data.list_loans()
        selected_index = next(
            (index for index, loan in enumerate(loans) if loan["id"] == selected_id),
            0,
        )
        selected = loans[selected_index] if loans else None
        if selected is not None:
            selected_id = selected["id"]
        footer = _key_binding_footer(
            term,
            [
                ("Loans", [("[j/k]", "select"), ("[a]", "add loan")]),
                ("Payments", [("[↑/↓]", "scroll"), ("[PgUp/PgDn]", "page")]),
                ("Return", [("[q/Esc]", "overview")]),
            ],
        )
        header = [term.bold("Manage loans"), ""]
        loan_rows: list[str] = []
        if loans:
            for loan in loans:
                completed = loan["amount"] - loan["current_principal"]
                completion_percent = (
                    completed * 100 + loan["amount"] // 2
                ) // loan["amount"]
                bar_width = 20
                filled_width = (
                    completed * bar_width + loan["amount"] // 2
                ) // loan["amount"]
                progress_bar = (
                    f"[{'#' * filled_width}{'-' * (bar_width - filled_width)}]"
                )
                loan_rows.extend(
                    [
                        f"{'>' if loan['id'] == selected_id else ' '} "
                        f"{loan['name']} — "
                        f"{format_amount(loan['current_principal'], data.get_currency())} / "
                        f"{format_amount(loan['amount'], data.get_currency())} "
                        f"({completion_percent}% completed)",
                        f"  {progress_bar}",
                    ]
                )
        else:
            loan_rows = ["No loans yet."]
        lines = header + loan_rows + [""]
        payments: list[CashFlowRecord] = []
        if selected is not None:
            payments = list(
                reversed(data.list_cash_flows(loan_id=selected["id"]))
            )
            lines.extend(
                [
                    term.bold(f"{selected['name']}"),
                    f"Current principal: "
                    f"{format_amount(selected['current_principal'], data.get_currency())}",
                    f"Total interest paid: "
                    f"{format_amount(selected['total_interest_paid'], data.get_currency())}",
                    "",
                    "Date       Total amount       Principal          Interest",
                ]
            )
            if not payments:
                lines.append("No payments recorded.")
        page_size = max(1, term.height - len(lines) - len(footer) - 2)
        payment_offset = min(
            payment_offset,
            max(0, len(payments) - page_size),
        )
        if payments:
            for payment in payments[payment_offset : payment_offset + page_size]:
                principal = payment["principal_amount"] or 0
                interest = abs(payment["amount"]) - principal
                lines.append(
                    f"{payment['occurred_at']:%Y-%m-%d}   "
                    f"{format_amount(abs(payment['amount']), data.get_currency()):>16}   "
                    f"{format_amount(principal, data.get_currency()):>16}   "
                    f"{format_amount(interest, data.get_currency()):>16}"
                )
        if notice:
            lines.extend(["", term.bold(notice)])
        lines.extend(["", *footer])
        print(term.home + term.clear + "\n".join(lines), end="", flush=True)

        key = term.inkey()
        if key.name == "KEY_ESCAPE" or key == "\x1b" or key.lower() == "q":
            return notice or "Loan management closed."
        if key.lower() == "a":
            try:
                notice, selected_id = _add_loan(term, data)
                payment_offset = 0
            except (IntegrityError, LookupError, ValueError) as error:
                notice = f"Could not create loan: {error}"
            continue
        if key.lower() in ("j", "k") and loans:
            direction = 1 if key.lower() == "j" else -1
            selected_index = (selected_index + direction) % len(loans)
            selected_id = loans[selected_index]["id"]
            payment_offset = 0
            notice = ""
        elif key.name in ("KEY_UP", "KEY_PAGE_UP"):
            payment_offset = max(
                0,
                payment_offset - (page_size if key.name == "KEY_PAGE_UP" else 1),
            )
        elif key.name in ("KEY_DOWN", "KEY_PAGE_DOWN"):
            payment_offset = min(
                max(0, len(payments) - page_size),
                payment_offset + (
                    page_size if key.name == "KEY_PAGE_DOWN" else 1
                ),
            )


def _markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _period_report_content(
    data: Data,
    period: PeriodRecord,
    currency: str,
) -> tuple[
    str,
    list[date],
    list[tuple[int, str, list[int]]],
    list[int],
]:
    cash_flows = data.list_cash_flows(
        start_date=period["start_date"],
        end_date=period["end_date"],
    )
    categories = data.list_categories()
    budget_report = data.get_period_budget_report(period["id"])
    budgets = {
        item["category_id"]: item["budget"]
        for item in budget_report["categories"]
    }
    flows_by_category: dict[int, list[CashFlowRecord]] = {
        category["id"]: [] for category in categories
    }
    for cash_flow in cash_flows:
        flows_by_category[cash_flow["category_id"]].append(cash_flow)
    graph_end = (
        period["end_date"].date()
        if period["end_date"] is not None
        else max(date.today(), max(
            (cash_flow["occurred_at"].date() for cash_flow in cash_flows),
            default=period["start_date"].date(),
        ))
    )
    graph_dates = sorted(
        {
            period["start_date"].date(),
            graph_end,
            *(cash_flow["occurred_at"].date() for cash_flow in cash_flows),
        }
    )

    def cumulative_values(flows: Sequence[CashFlowRecord]) -> list[int]:
        dated_amounts: dict[date, int] = {}
        for cash_flow in flows:
            flow_day = cash_flow["occurred_at"].date()
            dated_amounts[flow_day] = dated_amounts.get(flow_day, 0) + cash_flow["amount"]
        running_total = 0
        values = []
        for graph_day in graph_dates:
            running_total += dated_amounts.get(graph_day, 0)
            values.append(running_total)
        return values

    total_values = cumulative_values(cash_flows)

    def budget_status(category_ids: Sequence[int], balance: int) -> str:
        allocated = sum(budgets.get(category_id, 0) for category_id in category_ids)
        if not any(category_id in budgets for category_id in category_ids):
            return ""
        remaining = allocated + balance
        if remaining < 0:
            return (
                f" — Budget {format_amount(allocated, currency)}; "
                f"overspent {format_amount(abs(remaining), currency)}"
            )
        return (
            f" — Budget {format_amount(allocated, currency)}; "
            f"remaining {format_amount(remaining, currency)}"
        )

    lines = [
        f"# Period report: {_markdown_cell(period['name'])}",
        "",
        f"**Dates:** {period['start_date']:%Y-%m-%d} – "
        f"{period['end_date']:%Y-%m-%d}" if period["end_date"] else
        f"**Dates:** {period['start_date']:%Y-%m-%d} – Open",
        "",
    ]
    graph_categories: list[tuple[int, str, list[int]]] = []
    roots = [category for category in categories if category["parent_id"] is None]
    children_by_parent: dict[int, list[CategoryRecord]] = {}
    for category in categories:
        if category["parent_id"] is not None:
            children_by_parent.setdefault(category["parent_id"], []).append(category)

    grand_total = 0
    for root in roots:
        children = children_by_parent.get(root["id"], [])
        category_ids = [root["id"], *(child["id"] for child in children)]
        root_balance = sum(
            cash_flow["amount"]
            for category_id in category_ids
            for cash_flow in flows_by_category[category_id]
        )
        grand_total += root_balance
        root_label = f"[{root['symbol']}] {_markdown_cell(root['name'])}"
        lines.extend(
            [
                f"## {root_label}",
                f"**Subtotal:** {format_amount(root_balance, currency)}"
                f"{budget_status(category_ids, root_balance)}",
                "",
            ]
        )
        root_flows = [
            cash_flow
            for category_id in category_ids
            for cash_flow in flows_by_category[category_id]
        ]
        graph_categories.append(
            (root["id"], root_label, cumulative_values(root_flows))
        )
        own_flows = flows_by_category[root["id"]]
        if own_flows:
            lines.extend(
                [
                    f"### Transactions in {root_label}",
                    "| Date | Description | Amount |",
                    "| --- | --- | ---: |",
                ]
            )
            for cash_flow in own_flows:
                description = _markdown_cell(
                    cash_flow["description"] or "(no description)"
                )
                lines.append(
                    f"| {cash_flow['occurred_at']:%Y-%m-%d} | {description} | "
                    f"{format_amount(cash_flow['amount'], currency)} |"
                )
            lines.append("")

        for child in children:
            child_balance = sum(
                cash_flow["amount"] for cash_flow in flows_by_category[child["id"]]
            )
            child_label = f"[{child['symbol']}] {_markdown_cell(child['name'])}"
            lines.extend(
                [
                    f"### {child_label}",
                    f"**Subtotal:** {format_amount(child_balance, currency)}"
                    f"{budget_status([child['id']], child_balance)}",
                    "",
                ]
            )
            graph_categories.append(
                (
                    child["id"],
                    f"  {child_label}",
                    cumulative_values(flows_by_category[child["id"]]),
                )
            )
            child_flows = flows_by_category[child["id"]]
            if not child_flows:
                lines.extend(["_(No cash-flow items.)_", ""])
                continue
            lines.extend(
                [
                    "| Date | Description | Amount |",
                    "| --- | --- | ---: |",
                ]
            )
            for cash_flow in child_flows:
                description = _markdown_cell(
                    cash_flow["description"] or "(no description)"
                )
                lines.append(
                    f"| {cash_flow['occurred_at']:%Y-%m-%d} | {description} | "
                    f"{format_amount(cash_flow['amount'], currency)} |"
                )
            lines.append("")

    total_budget = sum(budgets.values())
    total_remaining = total_budget + grand_total
    lines.extend(
        [
            "## Period total",
            f"**Cash flow total:** {format_amount(grand_total, currency)}",
        ]
    )
    if budgets:
        status = (
            f"Overspent {format_amount(abs(total_remaining), currency)}"
            if total_remaining < 0
            else f"Remaining {format_amount(total_remaining, currency)}"
        )
        lines.append(
            f"**Allocated budget:** {format_amount(total_budget, currency)} — "
            f"{status}"
        )
    active_loans = [
        loan for loan in data.list_loans() if loan["current_principal"] > 0
    ]
    if active_loans:
        lines.extend(
            [
                "",
                "## Active loans",
                "",
                "| Loan | Principal remaining | Interest paid |",
                "| --- | ---: | ---: |",
            ]
        )
        for loan in active_loans:
            lines.append(
                f"| {_markdown_cell(loan['name'])} | "
                f"{format_amount(loan['current_principal'], currency)} | "
                f"{format_amount(loan['total_interest_paid'], currency)} |"
            )
    lines.extend(
        [
            "",
            "The graph shows cumulative balance over time. Category lines follow "
            "the graph-category selection; the total line includes all categories.",
            "",
            "![Cumulative balance over time](GRAPH_PATH)",
            "",
        ]
    )
    return "\n".join(lines), graph_dates, graph_categories, total_values


def _select_graph_categories(
    term: Terminal,
    categories: Sequence[tuple[int, str, list[int]]],
    selected_ids: set[int],
) -> set[int]:
    selection = set(selected_ids)
    index = 0
    while True:
        rows = [
            f"{'>' if row_index == index else ' '} "
            f"{'[x]' if category_id in selection else '[ ]'} {label}"
            for row_index, (category_id, label, _) in enumerate(categories)
        ]
        footer = _key_binding_footer(
            term,
            [
                ("Select", [("[↑/↓]", "move cursor"), ("[Space]", "toggle")]),
                ("All", [("[a]", "select all"), ("[n]", "select none")]),
                ("Done", [("[Enter/Esc]", "return")]),
            ],
        )
        visible_rows = max(1, term.height - len(footer) - 5)
        first_row = min(
            max(0, index - visible_rows + 1),
            max(0, len(rows) - visible_rows),
        )
        lines = [
            term.bold("Graph categories"),
            "",
            *rows[first_row : first_row + visible_rows],
            "",
            *footer,
        ]
        print(term.home + term.clear + "\n".join(lines), end="", flush=True)
        key = term.inkey()
        if key.name == "KEY_ESCAPE" or key == "\x1b" or key.name in (
            "KEY_ENTER",
            "KEY_RETURN",
        ) or key in ("\r", "\n"):
            return selection
        if not categories:
            continue
        if key.name == "KEY_UP":
            index = max(0, index - 1)
        elif key.name == "KEY_DOWN":
            index = min(len(categories) - 1, index + 1)
        elif key == " ":
            category_id = categories[index][0]
            if category_id in selection:
                selection.remove(category_id)
            else:
                selection.add(category_id)
        elif key.lower() == "a":
            selection = {category_id for category_id, _, _ in categories}
        elif key.lower() == "n":
            selection.clear()


def _save_period_report(
    markdown: str,
    period: PeriodRecord,
    graph_dates: Sequence[date],
    graph_categories: Sequence[tuple[int, str, list[int]]],
    total_values: Sequence[int],
    selected_ids: set[int],
    currency: str,
    output_dir: Path = Path("reports"),
) -> tuple[Path, Path]:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", period["name"]).strip("-")
    slug = slug or "period"
    stem = f"period-{period['id']}-{slug}"
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"{stem}.md"
    graph_path = output_dir / f"{stem}.png"

    selected = [
        (label, values)
        for category_id, label, values in graph_categories
        if category_id in selected_ids
    ]
    figure = Figure(figsize=(10, max(3.5, len(selected) * 0.45)))
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    for label, values in selected:
        axes.plot(
            graph_dates,
            [value / 100 for value in values],
            label=label,
            drawstyle="steps-post",
        )
    axes.plot(
        graph_dates,
        [value / 100 for value in total_values],
        label="Total (all categories)",
        color="#222222",
        linewidth=2.5,
        drawstyle="steps-post",
    )
    axes.set_title(f"Cumulative balance over time — {period['name']}")
    axes.set_xlabel("Date")
    axes.set_ylabel(f"Balance ({currency})")
    axes.grid(alpha=0.2)
    axes.legend()
    figure.autofmt_xdate()
    figure.tight_layout()
    figure.savefig(graph_path, dpi=160)
    markdown_path.write_text(
        markdown.replace("GRAPH_PATH", graph_path.name),
        encoding="utf-8",
    )
    return markdown_path, graph_path


def _show_period_report(
    term: Terminal,
    data: Data,
    period: PeriodRecord,
) -> str:
    currency = data.get_currency()
    markdown, graph_dates, graph_categories, total_values = _period_report_content(
        data, period, currency
    )
    lines = markdown.replace(
        "![Cumulative balance over time](GRAPH_PATH)", ""
    ).splitlines()
    selected_ids = {category_id for category_id, _, _ in graph_categories}
    offset = 0
    notice = ""
    while True:
        footer = _key_binding_footer(
            term,
            [
                ("Report", [("[↑/↓]", "scroll"), ("[g]", "graph categories")]),
                ("Export", [("[s]", "save Markdown + PNG")]),
                ("Return", [("[q/Esc]", "overview")]),
            ],
        )
        page_size = max(1, term.height - len(footer) - 5)
        offset = min(offset, max(0, len(lines) - page_size))
        visible = lines[offset : offset + page_size]
        screen_lines = [term.bold(f"Report: {period['name']}"), "", *visible]
        if notice:
            screen_lines.extend(["", term.bold(notice)])
        screen_lines.extend(["", *footer])
        print(term.home + term.clear + "\n".join(screen_lines), end="", flush=True)
        key = term.inkey()
        if key.name == "KEY_ESCAPE" or key == "\x1b" or key.lower() == "q":
            return notice or "Period report closed."
        if key.name in ("KEY_UP", "KEY_PAGE_UP"):
            offset = max(0, offset - (page_size if key.name == "KEY_PAGE_UP" else 1))
        elif key.name in ("KEY_DOWN", "KEY_PAGE_DOWN"):
            offset = min(
                max(0, len(lines) - page_size),
                offset + (page_size if key.name == "KEY_PAGE_DOWN" else 1),
            )
        elif key.lower() == "g":
            selected_ids = _select_graph_categories(
                term, graph_categories, selected_ids
            )
            notice = "Graph categories updated."
        elif key.lower() == "s":
            try:
                markdown_path, graph_path = _save_period_report(
                    markdown,
                    period,
                    graph_dates,
                    graph_categories,
                    total_values,
                    selected_ids,
                    currency,
                )
                notice = f"Saved {markdown_path} and {graph_path}."
            except OSError as error:
                notice = f"Could not save report: {error}"


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
    active_loans = [
        loan for loan in data.list_loans() if loan["current_principal"] > 0
    ]
    loan_id = None
    if active_loans:
        loan_options = "\n".join(
            f"{index}. {loan['name']} "
            f"({format_amount(loan['current_principal'], data.get_currency())} principal)"
            for index, loan in enumerate(active_loans, start=1)
        )
        loan_text = _read_line(
            term,
            "Loan number (blank for regular cash flow): ",
            prelude=f"Choose a loan or leave blank:\n{loan_options}\n",
        )
        if loan_text is None:
            return "Cash-flow creation cancelled."
        if loan_text:
            try:
                loan_id = active_loans[int(loan_text) - 1]["id"]
            except (ValueError, IndexError):
                raise ValueError("choose a valid loan number") from None

    amount_text = _read_line(
        term,
        "Total payment amount (e.g. 12.34): "
        if loan_id is not None
        else "Amount (+ income, - expense; e.g. 12.34): ",
    )
    if amount_text is None:
        return "Cash-flow creation cancelled."
    amount = parse_amount(amount_text)
    principal_amount = None
    if loan_id is not None:
        if amount <= 0:
            raise ValueError("loan payment amount must be greater than zero")
        principal_text = _read_line(term, "Principal amount paid: ")
        if principal_text is None:
            return "Cash-flow creation cancelled."
        principal_amount = parse_amount(principal_text)
        amount = -amount

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
        loan_id=loan_id,
        principal_amount=principal_amount,
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
    principal_amount = cash_flow["principal_amount"]
    if cash_flow["loan_id"] is not None:
        principal_default = f"{Decimal(principal_amount or 0) / 100:.2f}"
        principal_text = _read_line(
            term, "Principal amount paid: ", principal_default
        )
        if principal_text is None:
            return "Cash-flow edit cancelled."
        principal_amount = parse_amount(principal_text)
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
        cash_flow["loan_id"],
        principal_amount,
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
    calendar_month: tuple[int, int] | None = None
    cash_flow_days: set[date] = set()
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
                selected_month = (selected_day.year, selected_day.month)
                if calendar_month != selected_month:
                    month_end = date(
                        selected_day.year,
                        selected_day.month,
                        calendar.monthrange(*selected_month)[1],
                    )
                    month_cash_flows = data.list_cash_flows(
                        start_date=datetime.combine(
                            selected_day.replace(day=1), time.min
                        ),
                        end_date=datetime.combine(month_end, time.max),
                    )
                    cash_flow_days = {
                        cash_flow["occurred_at"].date()
                        for cash_flow in month_cash_flows
                    }
                    calendar_month = selected_month
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
                budget_report = (
                    data.get_period_budget_report(selected_period["id"])
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
                        budget_report,
                        cash_flow_days,
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
                    calendar_month = None
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
                elif key.lower() == "b":
                    try:
                        notice = _manage_budgets(term, data)
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not manage budgets: {error}"
                elif key.lower() == "l":
                    try:
                        notice = _manage_loans(term, data)
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not manage loans: {error}"
                elif key.lower() == "v":
                    if selected_period is None:
                        notice = "Select a day inside a period first."
                    else:
                        try:
                            notice = _show_period_report(
                                term,
                                data,
                                selected_period,
                            )
                        except (IntegrityError, LookupError, ValueError) as error:
                            notice = f"Could not display period report: {error}"
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
                    calendar_month = None
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
