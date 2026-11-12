import contextlib
import io
import re
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from main import (
    _calendar_lines,
    _key_binding_footer,
    _loan_completion_estimate,
    _manage_loans,
    _manage_savings_targets,
    _add_cash_flow,
    main,
    _period_report_content,
    _periods_for_day,
    _period_date,
    _period_end_datetime,
    _report_screen_line,
    _select_graph_categories,
    _save_period_report,
    _screen_update,
    _show_period_report,
    format_amount,
    month_grid,
    parse_amount,
    render_screen,
    shift_month,
)
from data import Data


class FakeTerminal:
    width = 100
    height = 40
    home = ""
    clear = ""
    clear_eol = ""
    normal = ""
    reverse = ""

    @staticmethod
    def bold(text):
        return text

    @staticmethod
    def red(text):
        return f"<red>{text}</red>"

    @staticmethod
    def yellow(text):
        return f"<yellow>{text}</yellow>"

    @staticmethod
    def center(text, width=None):
        return text.center(width or 100)

    @staticmethod
    def length(text):
        return len(re.sub(r"<[^>]+>", "", text))

    def __getattr__(self, name):
        if name.startswith("on_"):
            return f"<{name}>"
        if name in {
            "cyan",
            "green",
            "magenta",
            "white",
            "bright_black",
        }:
            return lambda text: f"<{name}>{text}</{name}>"
        raise AttributeError(name)

    @staticmethod
    def move_yx(row, column):
        return f"<move:{row},{column}>"


class FakeKey(str):
    @property
    def is_sequence(self):
        return False

    @property
    def name(self):
        return {
            "down": "KEY_DOWN",
            "up": "KEY_UP",
            "\r": "KEY_ENTER",
            "\x1b": "KEY_ESCAPE",
        }.get(str(self), "")


class ScriptedTerminal(FakeTerminal):
    def __init__(self, keys):
        self.keys = iter(keys)

    def inkey(self):
        return FakeKey(next(self.keys))


class UiHelperTests(unittest.TestCase):
    def test_calendar_grid_has_all_days_and_monday_first(self):
        weeks = month_grid(2026, 11)
        days = [day for week in weeks for day in week if day is not None]

        self.assertEqual(len(weeks[0]), 7)
        self.assertEqual(days[0], date(2026, 11, 1))
        self.assertEqual(days[-1], date(2026, 11, 30))
        self.assertEqual(weeks[0][0], None)
        self.assertEqual(weeks[0][6], date(2026, 11, 1))

    def test_month_shifting_clamps_day_to_target_month(self):
        self.assertEqual(shift_month(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(shift_month(date(2026, 3, 31), -1), date(2026, 2, 28))
        self.assertEqual(shift_month(date(2024, 1, 31), 1), date(2024, 2, 29))

    def test_amount_entry_converts_currency_units_to_minor_units(self):
        self.assertEqual(parse_amount("125"), 12_500)
        self.assertEqual(parse_amount("-12.34"), -1_234)
        self.assertEqual(format_amount(-1_234), "-$12.34")
        self.assertEqual(format_amount(1_234, "USD"), "USD 12.34")


        with self.assertRaises(ValueError):
            parse_amount("1.234")
        with self.assertRaises(ValueError):
            parse_amount("not an amount")

    def test_screen_renders_selected_date_and_shortcuts(self):
        terminal = FakeTerminal()
        screen = render_screen(
            terminal,
            date(2026, 10, 27),
            [],
            None,
        )

        self.assertIn("Tuesday, 27 October 2026", screen)
        plain_screen = re.sub(r"</?[a-z_]+>", "", screen)
        self.assertIn("Navigate:", plain_screen)
        self.assertIn("Cash flows:", plain_screen)
        self.assertIn("<yellow>[n]</yellow> new", screen)
        self.assertIn("<yellow>[c]</yellow> add category", screen)
        self.assertIn("<yellow>[v]</yellow> report", screen)
        self.assertIn("<yellow>[l]</yellow> manage loans", screen)
        self.assertIn("<yellow>[t]</yellow> savings targets", screen)
        self.assertIn("─" * 80, screen)

    def test_dashboard_shows_separate_loan_and_savings_totals(self):
        screen = render_screen(
            FakeTerminal(),
            date(2026, 10, 27),
            [],
            None,
            financial_totals={
                "loans_pending": 1_234_500,
                "savings_accrued": 750_000,
            },
        )

        self.assertIn("┌", screen)
        plain_screen = re.sub(r"</?[a-z_]+>", "", screen)
        self.assertIn("Loans remaining: $12,345.00", plain_screen)
        self.assertIn("Savings accrued: $7,500.00", plain_screen)
        self.assertNotIn("Net worth", screen)
        plain_screen = re.sub(r"</?[a-z_]+>", "", screen)
        self.assertIn("┌" + "─" * 98 + "┐", plain_screen)

    def test_dashboard_boxes_wide_panels_to_match_manual_layout(self):
        terminal = FakeTerminal()
        terminal.width = 150
        screen = render_screen(
            terminal,
            date(2026, 10, 27),
            [],
            None,
        )

        self.assertIn("╭─ CALENDAR", screen)
        self.assertIn("╭─ CASH FLOWS", screen)
        self.assertIn("╭─ PERIOD BALANCES", screen)
        self.assertIn("╰", screen)
        self.assertNotIn(" │ ", screen)

    def test_dashboard_limits_many_categories_to_terminal_height(self):
        terminal = FakeTerminal()
        terminal.width = 150
        terminal.height = 40
        period = {
            "id": 1,
            "name": "Annual",
            "start_date": datetime(2026, 1, 1),
            "end_date": None,
        }
        categories = [
            {
                "category_id": category_id,
                "category_name": f"Category {category_id}",
                "parent_id": None,
                "is_parent": False,
                "balance": -100,
            }
            for category_id in range(1, 21)
        ]
        screen = render_screen(
            terminal,
            date(2026, 10, 27),
            [period],
            {"period": period, "categories": categories, "total": -2_000},
        )

        self.assertLessEqual(len(screen.splitlines()), terminal.height)
        self.assertIn("more categories; press [v] for report", screen)
        self.assertIn("Total", screen)

    def test_screen_updates_only_changed_rows_without_clearing_terminal(self):
        terminal = FakeTerminal()
        terminal.home = "<home>"
        terminal.clear = "<clear>"
        terminal.clear_eol = "<clear-eol>"

        initial, previous_lines = _screen_update(terminal, "first\nsecond", None)
        unchanged, same_lines = _screen_update(
            terminal, "first\nsecond", previous_lines
        )
        changed, changed_lines = _screen_update(
            terminal, "first\nupdated\nthird", previous_lines
        )

        self.assertEqual(initial, "<home><clear>first\nsecond")
        self.assertEqual(unchanged, "")
        self.assertEqual(same_lines, previous_lines)
        self.assertEqual(
            changed,
            "<move:1,0>updated<clear-eol><move:2,0>third<clear-eol>",
        )
        self.assertEqual(changed_lines, ["first", "updated", "third"])

    def test_key_binding_footer_wraps_long_groups_to_terminal_width(self):
        terminal = FakeTerminal()
        terminal.width = 48
        footer = _key_binding_footer(
            terminal,
            [
                (
                    "Manage",
                    [
                        ("[↑/↓]", "select"),
                        ("[a]", "add"),
                        ("[e]", "edit"),
                        ("[d]", "delete"),
                    ],
                )
            ],
        )

        self.assertGreater(len(footer), 2)
        self.assertTrue(all(terminal.length(line) <= terminal.width for line in footer))

    def test_period_date_entry_parses_iso_dates_and_open_ends(self):
        self.assertEqual(_period_date("2026-10-27", "start date"), date(2026, 10, 27))
        self.assertEqual(
            _period_end_datetime("2026-10-27"),
            datetime(2026, 10, 27, 23, 59, 59, 999999),
        )
        self.assertIsNone(_period_end_datetime(""))
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            _period_date("27/10/2026", "start date")
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            _period_date("20261027", "start date")

    def test_calendar_marks_period_days_with_the_period_color(self):
        terminal = FakeTerminal()
        period = {
            "id": 1,
            "name": "Payday",
            "start_date": datetime(2026, 10, 1),
            "end_date": datetime(2026, 10, 31, 23, 59, 59),
        }

        screen = render_screen(
            terminal,
            date(2026, 10, 27),
            [period],
            None,
        )

        self.assertIn("<green>", screen)
        self.assertIn(
            "Period: <yellow><</yellow>Payday (1/1)<yellow>></yellow>",
            screen,
        )

    def test_calendar_marks_days_with_cash_flow_items(self):
        days_with_cash_flows = {date(2026, 10, 7), date(2026, 10, 27)}

        lines = _calendar_lines(
            FakeTerminal(),
            date(2026, 10, 27),
            [],
            days_with_cash_flows,
        )

        self.assertIn("  7*", "\n".join(lines))
        self.assertIn(" 27*", "\n".join(lines))
        self.assertIn("* Cash-flow items", lines)

    def test_calendar_uses_one_row_and_lists_overlapping_periods(self):
        periods = [
            {
                "id": 1,
                "name": "Earlier",
                "start_date": datetime(2026, 10, 1),
                "end_date": datetime(2026, 10, 31, 23, 59, 59),
            },
            {
                "id": 2,
                "name": "Second",
                "start_date": datetime(2026, 10, 2),
                "end_date": datetime(2026, 10, 31, 23, 59, 59),
            },
            {
                "id": 3,
                "name": "Third",
                "start_date": datetime(2026, 10, 2),
                "end_date": datetime(2026, 10, 31, 23, 59, 59),
            },
        ]

        lines = _calendar_lines(FakeTerminal(), date(2026, 10, 2), periods)
        first_week = lines[2]

        self.assertIn("<green>  2 ", first_week)
        self.assertNotIn("<magenta>", first_week)
        self.assertNotIn("<cyan>", first_week)
        self.assertIn("Earlier", "\n".join(lines))
        self.assertIn("Second", "\n".join(lines))
        self.assertIn("Third", "\n".join(lines))

    def test_balance_panel_shows_selected_period_index_when_periods_overlap(self):
        terminal = FakeTerminal()
        periods = [
            {
                "id": 1,
                "name": "November",
                "start_date": datetime(2026, 11, 1),
                "end_date": datetime(2026, 11, 30, 23, 59, 59),
            },
            {
                "id": 2,
                "name": "Payday",
                "start_date": datetime(2026, 11, 2),
                "end_date": None,
            },
        ]
        report = {"period": periods[1], "categories": [], "total": 0}

        screen = render_screen(
            terminal,
            date(2026, 11, 3),
            periods,
            report,
        )

        self.assertIn(
            "Period: <yellow><</yellow>Payday (2/2)<yellow>></yellow>",
            screen,
        )
        self.assertEqual(len(_periods_for_day(date(2026, 11, 3), periods)), 2)

    def test_balance_panel_indents_children_and_colors_negative_balances(self):
        terminal = FakeTerminal()
        period = {
            "id": 1,
            "name": "Payday",
            "start_date": datetime(2026, 10, 1),
            "end_date": None,
        }
        report = {
            "period": period,
            "categories": [
                {
                    "category_id": 1,
                    "category_name": "Essentials",
                    "parent_id": None,
                    "is_parent": True,
                    "balance": -15_000,
                },
                {
                    "category_id": 2,
                    "category_name": "Groceries",
                    "parent_id": 1,
                    "is_parent": False,
                    "balance": -5_000,
                },
                {
                    "category_id": 3,
                    "category_name": "Travel",
                    "parent_id": None,
                    "is_parent": False,
                    "balance": 0,
                },
                {
                    "category_id": 4,
                    "category_name": "Transport",
                    "parent_id": None,
                    "is_parent": True,
                    "balance": -3_000,
                },
                {
                    "category_id": 5,
                    "category_name": "Transit",
                    "parent_id": 4,
                    "is_parent": False,
                    "balance": -2_500,
                },
            ],
            "total": -18_000,
        }
        budget_report = {
            "period": period,
            "categories": [
                {
                    "category_id": 1,
                    "category_name": "Essentials",
                    "budget": 20_000,
                    "balance": -10_000,
                    "remaining": 10_000,
                },
                {
                    "category_id": 2,
                    "category_name": "Groceries",
                    "budget": 5_000,
                    "balance": -5_000,
                    "remaining": 0,
                },
                {
                    "category_id": 5,
                    "category_name": "Transit",
                    "budget": 10_000,
                    "balance": -2_500,
                    "remaining": 7_500,
                },
            ],
            "total_budget": 35_000,
            "total_balance": -17_500,
            "total_remaining": 17_500,
        }

        screen = render_screen(
            terminal,
            date(2026, 10, 27),
            [period],
            report,
            currency="€",
            budget_report=budget_report,
        )

        self.assertIn("Essentials", screen)
        self.assertIn("└─ Groceries", screen)
        self.assertIn("<red>-€100.00</red>", screen)
        plain_screen = re.sub(r"</?[a-z_]+>", "", screen)
        balance_rows = [
            line.split("│")[1]
            for line in plain_screen.splitlines()
            if "Essentials" in line or "Groceries" in line
        ]
        self.assertEqual(len(balance_rows), 2)
        self.assertIn("Essentials", balance_rows[0])
        self.assertIn("Groceries", balance_rows[1])
        amount_ends = [
            line.index(amount) + len(amount)
            for line, amount in zip(balance_rows, ("-€100.00", "-€50.00"))
        ]
        self.assertEqual(amount_ends[0], amount_ends[1])
        budget_ends = [
            line.index(" left)") + len(" left)") for line in balance_rows
        ]
        self.assertEqual(budget_ends[0], budget_ends[1])
        self.assertIn("(€100.00/€200.00 left)", balance_rows[0])
        self.assertIn("(€0.00/€50.00 left)", balance_rows[1])
        transport_row = next(
            line for line in plain_screen.splitlines() if "Transport" in line
        )
        self.assertIn("-€5.00", transport_row)
        self.assertNotIn("left)", transport_row)
        self.assertIn("Personal finance  ·  €", plain_screen)
        self.assertIn("Travel", screen)

    def test_period_report_groups_transactions_budgets_and_exports_png(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            data = Data(str(Path(temporary_directory) / "finance.db"))
            try:
                period = data.create_period(
                    datetime(2026, 10, 1),
                    datetime(2026, 10, 31, 23, 59, 59),
                    "October",
                )
                parent = data.create_category("Home")
                child = data.create_category("Utilities", parent["id"])
                overspent = data.create_category("Repairs", parent["id"])
                data.create_budget(10_000, parent["id"], period["id"])
                data.create_budget(20_000, child["id"], period["id"])
                data.create_budget(1_000, overspent["id"], period["id"])
                data.create_cash_flow(
                    -500, parent["id"], datetime(2026, 10, 2), "Direct | item"
                )
                data.create_cash_flow(
                    -2_500, child["id"], datetime(2026, 10, 3), "Water bill"
                )
                data.create_cash_flow(
                    -2_000, overspent["id"], datetime(2026, 10, 4), "Repair"
                )

                markdown, graph_dates, graph_categories, total_values = (
                    _period_report_content(data, period, "€")
                )
                self.assertIn("**Subtotal:** -€50.00 — Budget €310.00; remaining €260.00", markdown)
                self.assertIn("**Subtotal:** -€25.00 — Budget €200.00; remaining €175.00", markdown)
                self.assertIn("overspent €10.00", markdown)
                self.assertIn("Direct \\| item", markdown)
                self.assertEqual(
                    {
                        label.strip().split("] ", 1)[-1]: values
                        for _, label, values in graph_categories
                    },
                    {
                        "Home": [0, -500, -3_000, -5_000, -5_000],
                        "Utilities": [0, 0, -2_500, -2_500, -2_500],
                        "Repairs": [0, 0, 0, -2_000, -2_000],
                    },
                )
                self.assertEqual(total_values, [0, -500, -3_000, -5_000, -5_000])
                self.assertEqual(
                    graph_dates,
                    [
                        date(2026, 10, 1),
                        date(2026, 10, 2),
                        date(2026, 10, 3),
                        date(2026, 10, 4),
                        date(2026, 10, 31),
                    ],
                )

                markdown_path, graph_path = _save_period_report(
                    markdown,
                    period,
                    graph_dates,
                    graph_categories,
                    total_values,
                    {category_id for category_id, _, _ in graph_categories},
                    "€",
                    Path(temporary_directory) / "reports",
                )
                self.assertTrue(markdown_path.is_file())
                self.assertEqual(graph_path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                self.assertIn(f"]({graph_path.name})", markdown_path.read_text())
            finally:
                data.close()

    def test_period_report_lists_active_loans(self):
        data = Data(":memory:")
        try:
            category = data.create_category("Loan payment")
            period = data.create_period(
                datetime(2026, 10, 1), datetime(2026, 10, 31)
            )
            loan = data.create_loan("Car", 100_000)
            data.create_cash_flow(
                -10_000,
                category["id"],
                datetime(2026, 10, 5),
                "Payment",
                loan["id"],
                8_000,
            )

            markdown, _, _, _ = _period_report_content(data, period, "$")

            self.assertIn("## Active loans", markdown)
            self.assertIn("| Car | $920.00 | $20.00 |", markdown)
        finally:
            data.close()

    def test_period_report_renders_transactions_as_readable_items(self):
        terminal = FakeTerminal()
        line = _report_screen_line(
            terminal,
            r"| 2026-10-02 | Direct \| item | -€5.00 |",
        )

        self.assertEqual(
            re.sub(r"</?[a-z_]+>", "", line),
            "  2026-10-02  Direct | item  -€5.00",
        )
        self.assertEqual(
            _report_screen_line(terminal, "| Date | Description | Amount |"),
            "",
        )

    def test_period_report_renders_active_loans_as_readable_items(self):
        terminal = FakeTerminal()
        line = _report_screen_line(
            terminal,
            "| Car | $920.00 | $20.00 |",
        )

        self.assertEqual(
            re.sub(r"</?[a-z_]+>", "", line),
            "  Car  · Remaining: $920.00  · Interest paid: $20.00",
        )
        self.assertEqual(
            _report_screen_line(
                terminal,
                "| Loan | Principal remaining | Interest paid |",
            ),
            "",
        )

    def test_period_report_screen_uses_overview_panels_and_scrolls(self):
        data = Data(":memory:")
        try:
            category = data.create_category("Food")
            period = data.create_period(
                datetime(2026, 10, 1),
                datetime(2026, 10, 31, 23, 59, 59),
                "October",
            )
            data.create_budget(20_000, category["id"], period["id"])
            data.create_cash_flow(
                -5_000,
                category["id"],
                datetime(2026, 10, 5),
                "Groceries",
            )
            terminal = ScriptedTerminal(["down", "down", "q"])
            terminal.width = 100
            terminal.height = 18
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = _show_period_report(terminal, data, period)

            screen = output.getvalue()
            plain_screen = re.sub(r"</?[a-z_]+>", "", screen)
            self.assertIn("PICCIULI  /  PERIOD REPORT", plain_screen)
            self.assertIn("Cash flow total: -$50.00", plain_screen)
            self.assertIn("Budget remaining:", plain_screen)
            self.assertIn("╭─ REPORT DETAILS", plain_screen)
            self.assertIn("╰", plain_screen)
            self.assertIn("<move:", screen)
            self.assertLessEqual(len(plain_screen.splitlines()), terminal.height)
            self.assertEqual(result, "Period report closed.")
        finally:
            data.close()

    def test_loan_screen_shows_newest_payments_and_balance_summary(self):
        data = Data(":memory:")
        try:
            category = data.create_category("Loan payment")
            loan = data.create_loan("Car", 100_000)
            data.create_cash_flow(
                -10_000, category["id"], datetime(2026, 10, 5), "Older", loan["id"], 8_000
            )
            data.create_cash_flow(
                -5_000, category["id"], datetime(2026, 11, 5), "Newer", loan["id"], 5_000
            )
            repaid_loan = data.create_loan("Paid off", 1_000)
            data.create_cash_flow(
                -1_000,
                category["id"],
                datetime(2026, 12, 5),
                "Final payment",
                repaid_loan["id"],
                1_000,
            )
            data.create_loan("Longer student loan", 50_000)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = _manage_loans(ScriptedTerminal(["\x1b"]), data)

            screen = output.getvalue()
            self.assertIn("Current principal: $870.00", screen)
            self.assertIn("Total interest paid: $20.00", screen)
            self.assertIn("Remaining / Total", screen)
            self.assertIn("Progress", screen)
            self.assertIn("Completion", screen)
            self.assertIn("$870.00 / $1,000.00", screen)
            self.assertIn("[###-----------------]", screen)
            self.assertIn("Total principal: $1,370.00 remaining / $1,510.00", screen)
            self.assertIn("Total interest paid: $20.00", screen)
            self.assertIn("Overall progress: 9% completed", screen)
            plain_rows = [
                re.sub(r"</?[a-z_]+>", "", line)
                for line in screen.splitlines()
                if re.search(r"\[[#-]{20}\]", line)
            ]
            header_row = next(
                re.sub(r"</?[a-z_]+>", "", line)
                for line in screen.splitlines()
                if "Remaining / Total" in line
            )
            self.assertEqual(len(plain_rows), 3)
            self.assertEqual(
                {line.index("[") for line in plain_rows},
                {plain_rows[0].index("[")},
            )
            completion_column = header_row.index("Completion")
            self.assertEqual(
                {line.rindex("Jan 2028") if "Jan 2028" in line else
                 line.rindex("N/A") if "N/A" in line else line.rindex("Paid off")
                 for line in plain_rows},
                {completion_column},
            )
            progress_end = header_row.index("Progress") + len("Progress")
            principal_start = header_row.index("Remaining / Total")
            principal_end = header_row.index("Progress") - 2
            for line in plain_rows:
                progress_match = re.search(r"\s+(\d+%)\s{2}", line)
                self.assertIsNotNone(progress_match)
                assert progress_match is not None
                self.assertEqual(
                    progress_match.start(1) + len(progress_match.group(1)),
                    progress_end,
                )
                principal_cell = line[principal_start:principal_end]
                self.assertEqual(principal_cell.rstrip(), principal_cell)
            self.assertIn("Jan 2028", screen)
            self.assertIn("N/A", screen)
            self.assertIn("Paid off", screen)
            self.assertIn("[####################]", screen)
            self.assertLess(screen.index("2026-11-05"), screen.index("2026-10-05"))
            self.assertEqual(result, "Loan management closed.")
        finally:
            data.close()

    def test_loan_completion_estimate_uses_average_monthly_principal(self):
        loan = {
            "id": 1,
            "name": "Car",
            "amount": 100_000,
            "current_principal": 87_000,
            "total_interest_paid": 2_000,
        }
        payments = [
            {
                "id": 1,
                "amount": -10_000,
                "description": "First",
                "category_id": 1,
                "occurred_at": datetime(2026, 10, 5),
                "loan_id": 1,
                "principal_amount": 8_000,
            },
            {
                "id": 2,
                "amount": -5_000,
                "description": "Second",
                "category_id": 1,
                "occurred_at": datetime(2026, 11, 5),
                "loan_id": 1,
                "principal_amount": 5_000,
            },
        ]

        self.assertEqual(
            _loan_completion_estimate(loan, payments, date(2026, 11, 7)),
            "Jan 2028",
        )
        self.assertEqual(
            _loan_completion_estimate(loan, [], date(2026, 11, 7)),
            "N/A",
        )
        self.assertEqual(
            _loan_completion_estimate(
                loan,
                payments
                + [
                    {
                        "id": 3,
                        "amount": -20_000,
                        "description": "New borrowing",
                        "category_id": 1,
                        "occurred_at": datetime(2026, 11, 6),
                        "loan_id": 1,
                        "principal_amount": -20_000,
                    }
                ],
                date(2026, 11, 7),
            ),
            "N/A",
        )
        loan["current_principal"] = 0
        self.assertEqual(
            _loan_completion_estimate(loan, payments, date(2026, 11, 7)),
            "Paid off",
        )

    def test_loan_screen_clamps_progress_after_new_borrowing(self):
        data = Data(":memory:")
        try:
            category = data.create_category("Credit card")
            loan = data.create_loan("Credit line", 1_000)
            data.create_cash_flow(
                -2_000,
                category["id"],
                datetime(2026, 11, 5),
                "Purchase",
                loan["id"],
                -2_000,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                _manage_loans(ScriptedTerminal(["\x1b"]), data)

            screen = output.getvalue()
            self.assertIn("Current principal: $30.00", screen)
            self.assertIn("[--------------------]", screen)
            self.assertIn("0%", screen)
        finally:
            data.close()

    def test_savings_target_screen_shows_progress_and_contributions(self):
        data = Data(":memory:")
        try:
            category = data.create_category("Savings")
            target = data.create_savings_target("New car", 1_500_000)
            data.create_cash_flow(
                -250_000,
                category["id"],
                datetime(2026, 11, 5),
                "Monthly",
                savings_target_id=target["id"],
            )
            data.create_savings_target("Z Emergency reserve", 1_000_000)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = _manage_savings_targets(
                    ScriptedTerminal(["\x1b"]), data
                )

            screen = output.getvalue()
            self.assertIn("Total savings: $2,500.00 / $25,000.00", screen)
            self.assertIn("Overall progress: 10% completed", screen)
            self.assertIn("Accrued / Target", screen)
            self.assertIn("Progress", screen)
            self.assertIn("$2,500.00 / $15,000.00", screen)
            self.assertIn("$0.00 / $10,000.00", screen)
            self.assertIn("[###-----------------]", screen)
            plain_rows = [
                re.sub(r"</?[a-z_]+>", "", line)
                for line in screen.splitlines()
                if re.search(r"\[[#-]{20}\]", line)
            ]
            self.assertEqual(len(plain_rows), 2)
            header_row = next(
                re.sub(r"</?[a-z_]+>", "", line)
                for line in screen.splitlines()
                if "Accrued / Target" in line
            )
            self.assertEqual(
                {line.index("[") for line in plain_rows},
                {plain_rows[0].index("[")},
            )
            target_column_end = (
                header_row.index("Accrued / Target")
                + len("Accrued / Target")
            )
            for value in ("$2,500.00 / $15,000.00", "$0.00 / $10,000.00"):
                matching_row = next(line for line in plain_rows if value in line)
                self.assertEqual(
                    matching_row.index(value) + len(value),
                    target_column_end,
                )
            self.assertIn("Accrued: $2,500.00", screen)
            self.assertIn("2026-11-05", screen)
            self.assertEqual(result, "Savings-target management closed.")
        finally:
            data.close()

    def test_cash_flow_entry_links_savings_target_as_contribution(self):
        data = Data(":memory:")
        try:
            category = data.create_category("Savings")
            target = data.create_savings_target("New car", 1_500_000)
            keys = [
                *"Monthly saving",
                "\r",
                "1",
                "\r",
                *"2500.00",
                "\r",
                "1",
                "\r",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                message = _add_cash_flow(
                    ScriptedTerminal(keys),
                    data,
                    date(2026, 11, 5),
                    [category],
                )

            payment = data.list_cash_flows(savings_target_id=target["id"])[0]
            self.assertEqual(payment["amount"], -250_000)
            self.assertEqual(payment["savings_target_id"], target["id"])
            self.assertEqual(message, "Added cash flow: -$2,500.00.")
        finally:
            data.close()

    def test_cash_flow_entry_links_savings_target_withdrawal(self):
        data = Data(":memory:")
        try:
            category = data.create_category("Savings")
            target = data.create_savings_target("Emergency fund", 100_000)
            data.create_cash_flow(
                -75_000,
                category["id"],
                datetime(2026, 11, 4),
                "Deposit",
                savings_target_id=target["id"],
            )
            keys = [
                *"Emergency withdrawal",
                "\r",
                "1",
                "\r",
                *"-500.00",
                "\r",
                "1",
                "\r",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                message = _add_cash_flow(
                    ScriptedTerminal(keys),
                    data,
                    date(2026, 11, 5),
                    [category],
                )

            withdrawal = data.list_cash_flows(savings_target_id=target["id"])[1]
            self.assertEqual(withdrawal["amount"], 50_000)
            self.assertEqual(
                data.get_savings_target(target["id"])["accrued_amount"],
                25_000,
            )
            self.assertEqual(message, "Added cash flow: $500.00.")
        finally:
            data.close()

    def test_savings_target_history_displays_signed_net_changes(self):
        data = Data(":memory:")
        try:
            category = data.create_category("Savings")
            target = data.create_savings_target("Emergency fund", 100_000)
            data.create_cash_flow(
                -75_000,
                category["id"],
                datetime(2026, 11, 4),
                "Deposit",
                savings_target_id=target["id"],
            )
            data.create_cash_flow(
                25_000,
                category["id"],
                datetime(2026, 11, 5),
                "Withdrawal",
                savings_target_id=target["id"],
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                _manage_savings_targets(ScriptedTerminal(["\x1b"]), data)

            screen = output.getvalue()
            self.assertIn("Accrued: $500.00", screen)
            self.assertIn("Savings change", screen)
            self.assertIn("-$250.00", screen)
            self.assertIn("$750.00", screen)
        finally:
            data.close()

    def test_cash_flow_entry_links_loan_with_new_borrowing(self):
        data = Data(":memory:")
        try:
            category = data.create_category("Credit card")
            loan = data.create_loan("Credit line", 100_000)
            keys = [
                *"New purchase",
                "\r",
                "1",
                "\r",
                *"250.00",
                "\r",
                *"-250.00",
                "\r",
                "1",
                "\r",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                message = _add_cash_flow(
                    ScriptedTerminal(keys),
                    data,
                    date(2026, 11, 5),
                    [category],
                )

            purchase = data.list_cash_flows(loan_id=loan["id"])[0]
            self.assertEqual(purchase["amount"], -25_000)
            self.assertEqual(purchase["principal_amount"], -25_000)
            self.assertEqual(
                data.get_loan(loan["id"])["current_principal"],
                125_000,
            )
            self.assertEqual(message, "Added cash flow: -$250.00.")
        finally:
            data.close()

    def test_graph_category_selector_toggles_selected_category(self):
        categories = [
            (1, "Food", [0, -100]),
            (2, "Transport", [0, -50]),
        ]
        selection = _select_graph_categories(
            ScriptedTerminal(["down", " ", "\r"]),
            categories,
            {1, 2},
        )

        self.assertEqual(selection, {1})

    def test_selected_day_cash_flow_panel_shows_description_category_and_amount(self):
        terminal = FakeTerminal()
        category = {
            "id": 2,
            "name": "Groceries",
            "symbol": "GRO",
            "parent_id": 1,
            "parent_name": "Essentials",
        }
        cash_flow = {
            "id": 7,
            "amount": -1_250,
            "description": "Market",
            "category_id": 2,
            "occurred_at": datetime(2026, 10, 27, 9, 15),
            "loan_id": None,
            "principal_amount": None,
            "savings_target_id": None,
        }

        screen = render_screen(
            terminal,
            date(2026, 10, 27),
            [],
            None,
            [cash_flow],
            [category],
            "€",
            selected_cash_flow_id=7,
        )

        self.assertIn("Cash flows", screen)
        plain_screen = re.sub(r"</?[a-z_]+>", "", screen)
        self.assertIn("[GRO] -€12.50 - Market", plain_screen)
        self.assertIn("> [GRO]", plain_screen)
        self.assertIn("<red>-€12.50</red>", screen)
        self.assertLess(
            plain_screen.index("CALENDAR"),
            plain_screen.index("CASH FLOWS"),
        )
        self.assertLess(
            plain_screen.index("CASH FLOWS"),
            plain_screen.index("PERIOD BALANCES"),
        )

    def test_cash_flow_panel_shows_empty_day_message(self):
        screen = render_screen(
            FakeTerminal(),
            date(2026, 10, 27),
            [],
            None,
        )

        self.assertIn("No cash flows for this day.", screen)


class DemoProjectTests(unittest.TestCase):
    def test_demo_option_creates_a_populated_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "showcase.db"
            self.assertEqual(main(["--demo", str(database_path)]), 0)

            data = Data(str(database_path))
            try:
                categories = data.list_categories()
                self.assertTrue(
                    any(category["parent_id"] is not None for category in categories)
                )
                periods = data.list_periods()
                self.assertEqual(len(periods), 5)
                current_period = next(
                    period
                    for period in periods
                    if period["name"] == date.today().strftime("%B %Y")
                )
                self.assertIsNone(current_period["end_date"])
                self.assertTrue(data.list_budgets(current_period["id"]))

                cash_flows = data.list_cash_flows()
                self.assertGreaterEqual(len(cash_flows), 30)
                self.assertTrue(
                    any(flow["loan_id"] is not None for flow in cash_flows)
                )
                self.assertTrue(
                    any(
                        flow["savings_target_id"] is not None
                        for flow in cash_flows
                    )
                )
                self.assertGreater(data.list_loans()[0]["total_interest_paid"], 0)
                self.assertGreater(
                    data.list_savings_targets()[0]["accrued_amount"], 0
                )
            finally:
                data.close()

    def test_demo_option_does_not_overwrite_an_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "existing.db"
            database_path.write_text("keep this file")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["--demo", str(database_path)])

            self.assertEqual(result, 1)
            self.assertEqual(database_path.read_text(), "keep this file")
            self.assertIn("already exists", output.getvalue())


if __name__ == "__main__":
    unittest.main()
