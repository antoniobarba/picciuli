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


def _period_for_day(day: date, periods: Sequence[PeriodRecord]) -> PeriodRecord | None:
    for period in periods:
        if (
            period["start_date"].date() <= day
            and (
                period["end_date"] is None
                or period["end_date"].date() >= day
            )
        ):
            return period
    return None


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
    selected_day: date,
    cash_flows: Sequence[CashFlowRecord],
    categories: Sequence[CategoryRecord],
    currency: str,
    width: int,
) -> list[str]:
    lines = [term.bold("Cash flows"), selected_day.strftime("%A, %d %b"), ""]
    category_names = {category["id"]: category["name"] for category in categories}
    if not cash_flows:
        lines.append("No cash flows for this day.")
        return lines

    content_width = max(12, width)
    for cash_flow in cash_flows:
        amount = format_amount(cash_flow["amount"], currency)
        if cash_flow["amount"] < 0:
            amount = term.red(amount)
        time_label = cash_flow["occurred_at"].strftime("%H:%M")
        lines.append(f"{time_label}  {amount}")

        category_name = category_names.get(cash_flow["category_id"], "Unknown")
        description = cash_flow["description"] or "(no description)"
        detail = f"  {category_name} / {description}"
        if term.length(detail) > content_width:
            detail = detail[: max(0, content_width - 1)] + "…"
        lines.append(detail)
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
) -> str:
    left_width = 30
    title = term.bold(f"Picciuli - Personal Finance ({currency})")
    calendar_panel = [term.bold("Calendar"), *_calendar_lines(term, selected_day, periods)]
    cash_width = max(12, (term.width - left_width - 6) // 2)
    balance_width = max(12, term.width - left_width - cash_width - 6)
    cash_panel = _cash_flow_lines(
        term,
        selected_day,
        cash_flows,
        categories,
        currency,
        cash_width,
    )
    balance_panel = [term.bold("Period balances")]

    selected_period = _period_for_day(selected_day, periods)
    if selected_period is None:
        balance_panel.extend(
            [
                term.bold("No period covers this day."),
                "Press n to start a period here.",
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
                term.bold(f"Period: {selected_period['name']}"),
                f"{selected_period['start_date']:%d %b %Y} - {end_label}",
                "",
            ]
        )
        if report is None:
            balance_panel.append("No balance data available.")
        else:
            report_categories = report["categories"]
            if not report_categories:
                balance_panel.append("No categories yet. Press c to add one.")
            else:
                for item in report_categories:
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
        for panel in (calendar_panel, cash_panel, balance_panel):
            lines.extend(panel)
            lines.append("")

    lines.extend(
        [
            "",
            "←/→ day  ↑/↓ week  [/] month  n new period  r rename period",
            "a add cash flow  c add category  u currency  q quit",
        ]
    )
    if notice:
        lines.append("")
        lines.append(term.bold(notice))
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
        print(
            term.home + term.clear + prelude + prompt + shown,
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


def _add_category(term: Terminal, data: Data) -> str:
    name = _read_line(term, "New category name (Esc cancels): ")
    if name is None:
        return "Category creation cancelled."
    roots = [category for category in data.list_categories() if category["parent_id"] is None]
    parent_id = None
    if roots:
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
    category = data.create_category(name, parent_id)
    return f"Created category: {category['name']}."


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


def run_ui(database_path: Path) -> None:
    term = Terminal()
    data = Data(str(database_path))
    selected_day = date.today()
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
                selected_period = _period_for_day(selected_day, periods)
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
                elif key.name == "KEY_RIGHT":
                    selected_day += timedelta(days=1)
                elif key.name == "KEY_UP":
                    selected_day -= timedelta(days=7)
                elif key.name == "KEY_DOWN":
                    selected_day += timedelta(days=7)
                elif key == "[":
                    selected_day = shift_month(selected_day, -1)
                elif key == "]":
                    selected_day = shift_month(selected_day, 1)
                elif key.lower() == "n":
                    try:
                        notice = _add_period(term, data, selected_day)
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not create period: {error}"
                elif key.lower() == "r":
                    try:
                        notice = _rename_period(
                            term, data, _period_for_day(selected_day, periods)
                        )
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not rename period: {error}"
                elif key.lower() == "c":
                    try:
                        notice = _add_category(term, data)
                    except (IntegrityError, LookupError, ValueError) as error:
                        notice = f"Could not create category: {error}"
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
