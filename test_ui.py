import re
import unittest
from datetime import date, datetime

from main import (
    _periods_for_day,
    _period_date,
    _period_end_datetime,
    format_amount,
    month_grid,
    parse_amount,
    render_screen,
    shift_month,
)


class FakeTerminal:
    width = 100
    home = ""
    clear = ""
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
        raise AttributeError(name)


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
        self.assertIn("<yellow>[n]</yellow> new period", screen)
        self.assertIn("<yellow>[a]</yellow> add cash flow", screen)
        self.assertIn("<yellow>[u]</yellow> currency", screen)
        self.assertIn("<yellow>[n]</yellow> new period - <yellow>[r]</yellow>", screen)
        self.assertIn("<yellow>[p]</yellow> manage periods", screen)
        self.assertIn("-" * 80, screen)

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

        self.assertIn("<on_blue>", screen)
        self.assertIn(
            "Period: <yellow><</yellow>Payday (1/1)<yellow>></yellow>",
            screen,
        )

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
            ],
            "total": -15_000,
        }

        screen = render_screen(
            terminal,
            date(2026, 10, 27),
            [period],
            report,
            currency="€",
        )

        self.assertIn("Essentials", screen)
        self.assertIn("└─ Groceries", screen)
        self.assertIn("<red>-€150.00</red>", screen)
        self.assertIn("(€)", screen)
        lines = screen.splitlines()
        travel_index = next(
            index for index, line in enumerate(lines) if "Travel" in line
        )
        self.assertEqual(lines[travel_index - 1].split(" │ ")[-1], "")

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
        plain_screen = re.sub(r"</?red>", "", screen)
        self.assertIn("[GRO] -€12.50 - Market", plain_screen)
        self.assertIn("> [GRO]", screen)
        self.assertIn("<red>-€12.50</red>", screen)
        self.assertLess(screen.index("Calendar"), screen.index("Cash flows"))
        self.assertLess(screen.index("Cash flows"), screen.index("Period balances"))

    def test_cash_flow_panel_shows_empty_day_message(self):
        screen = render_screen(
            FakeTerminal(),
            date(2026, 10, 27),
            [],
            None,
        )

        self.assertIn("No cash flows for this day.", screen)


if __name__ == "__main__":
    unittest.main()
