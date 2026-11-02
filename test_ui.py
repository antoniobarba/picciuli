import unittest
from datetime import date, datetime

from main import format_amount, month_grid, parse_amount, render_screen, shift_month


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
    def center(text, width=None):
        return text.center(width or 100)

    @staticmethod
    def length(text):
        return len(text)

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
        self.assertIn("n new period", screen)
        self.assertIn("a add cash flow", screen)
        self.assertIn("u currency", screen)

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
        self.assertIn("Period: Payday", screen)

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

    def test_selected_day_cash_flow_panel_shows_description_category_and_amount(self):
        terminal = FakeTerminal()
        category = {
            "id": 2,
            "name": "Groceries",
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
        )

        self.assertIn("Cash flows", screen)
        self.assertIn("09:15", screen)
        self.assertIn("Groceries / Market", screen)
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
