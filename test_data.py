import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from data import Budget, Category, Data


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = str(Path(self.temp_dir.name) / "finance.db")
        self.data = Data(self.database_path)

    def tearDown(self):
        self.data.close()
        self.temp_dir.cleanup()

    def test_creates_expected_schema(self):
        inspector = inspect(self.data.engine)

        self.assertEqual(
            set(inspector.get_table_names()),
            {"categories", "cash_flows", "periods", "budgets", "settings"},
        )
        self.assertIn(
            "parent_id",
            {column["name"] for column in inspector.get_columns("categories")},
        )
        self.assertIn(
            "symbol",
            {column["name"] for column in inspector.get_columns("categories")},
        )
        self.assertIn(
            "sort_order",
            {column["name"] for column in inspector.get_columns("categories")},
        )
        self.assertEqual(
            {column["name"] for column in inspector.get_columns("cash_flows")},
            {"id", "amount", "description", "category_id", "occurred_at"},
        )
        period_columns = {
            column["name"]: column
            for column in inspector.get_columns("periods")
        }
        self.assertIn("name", period_columns)
        self.assertTrue(period_columns["end_date"]["nullable"])

    def test_outdated_database_schema_fails_with_recovery_guidance(self):
        old_database = str(Path(self.temp_dir.name) / "old.db")
        connection = sqlite3.connect(old_database)
        try:
            connection.execute(
                """
                CREATE TABLE periods (
                    id INTEGER PRIMARY KEY,
                    start_date DATETIME NOT NULL,
                    end_date DATETIME NOT NULL
                )
                """
            )
        finally:
            connection.close()

        with self.assertRaisesRegex(RuntimeError, "Use a new database file"):
            Data(old_database)

    def test_category_crud_and_ordering(self):
        food = self.data.create_category(" Food ")
        housing = self.data.create_category("Housing")

        self.assertEqual(
            food,
            {
                "id": 1,
                "name": "Food",
                "symbol": "F",
                "parent_id": None,
                "parent_name": None,
            },
        )
        self.assertEqual(self.data.get_category(food["id"]), food)
        self.assertEqual(
            self.data.list_categories(),
            [food, housing],
        )
        self.assertEqual(
            self.data.update_category(food["id"], "Groceries"),
            {
                "id": food["id"],
                "name": "Groceries",
                "symbol": "F",
                "parent_id": None,
                "parent_name": None,
            },
        )

        self.data.delete_category(housing["id"])
        self.assertEqual(
            self.data.list_categories(),
            [
                {
                    "id": food["id"],
                    "name": "Groceries",
                    "symbol": "F",
                    "parent_id": None,
                    "parent_name": None,
                }
            ],
        )

    def test_category_validation_and_uniqueness(self):
        self.data.create_category("Food")
        self.data.create_category("Other")
        with self.assertRaises(ValueError):
            self.data.create_category("  ")
        with self.assertRaises(IntegrityError):
            self.data.create_category("Food")
        with self.assertRaises(IntegrityError):
            self.data.update_category(2, "Food")
        with self.assertRaises(LookupError):
            self.data.get_category(999)

        self.assertEqual(
            self.data.list_categories(),
            [
                {
                    "id": 1,
                    "name": "Food",
                    "symbol": "F",
                    "parent_id": None,
                    "parent_name": None,
                },
                {
                    "id": 2,
                    "name": "Other",
                    "symbol": "O",
                    "parent_id": None,
                    "parent_name": None,
                },
            ],
        )

    def test_category_symbol_validation_and_update(self):
        category = self.data.create_category("Coffee", symbol="CAF")
        self.assertEqual(category["symbol"], "CAF")
        renamed = self.data.update_category(category["id"], "Cafes")
        self.assertEqual(renamed["symbol"], "CAF")
        changed = self.data.update_category(
            category["id"], "Cafes", symbol="CAFE"
        )
        self.assertEqual(changed["symbol"], "CAFE")

        with self.assertRaises(ValueError):
            self.data.create_category("Empty symbol", symbol=" ")
        with self.assertRaises(ValueError):
            self.data.create_category("Long symbol", symbol="1234567890123")
        with self.assertRaises(TypeError):
            self.data.create_category("Wrong symbol", symbol=123)

    def test_category_hierarchy_validation_and_ordering(self):
        essentials = self.data.create_category("Essentials", symbol="ESS")
        groceries = self.data.create_category("Groceries", essentials["id"], "GRO")
        bills = self.data.create_category("Bills", essentials["id"], "BIL")
        other = self.data.create_category("Income", symbol="INC")

        self.assertEqual(
            self.data.list_categories(),
            [
                essentials,
                groceries,
                bills,
                other,
            ],
        )
        self.assertEqual(groceries["parent_id"], essentials["id"])
        self.assertEqual(groceries["parent_name"], "Essentials")
        self.assertEqual(groceries["symbol"], "GRO")
        with self.assertRaises(ValueError):
            self.data.create_category("Nested", groceries["id"])
        with self.assertRaises(LookupError):
            self.data.create_category("Orphan", 999)
        with self.assertRaises(ValueError):
            self.data.update_category(essentials["id"], "Essentials", other["id"])
        with self.assertRaises(ValueError):
            self.data.update_category(other["id"], "Income", other["id"])
        with self.assertRaises(ValueError):
            self.data.delete_category(essentials["id"])

        moved = self.data.update_category(
            groceries["id"], "Food shop", other["id"], "SHOP"
        )
        self.assertEqual(moved["parent_id"], other["id"])
        self.assertEqual(moved["parent_name"], "Income")
        self.assertEqual(moved["symbol"], "SHOP")

    def test_category_order_can_be_changed_and_is_used_by_period_balances(self):
        first = self.data.create_category("First")
        second = self.data.create_category("Second")
        first_child = self.data.create_category("First child", first["id"])
        self.data.create_category("Second child", first["id"])
        period = self.data.create_period(datetime(2026, 10, 1))

        self.data.update_category(second["id"], "Second", position=1)
        self.data.update_category(
            first_child["id"], "First child", first["id"], position=2
        )

        self.assertEqual(
            [category["name"] for category in self.data.list_categories()],
            ["Second", "First", "Second child", "First child"],
        )
        report = self.data.get_period_balances(period["id"])
        self.assertEqual(
            [category["category_name"] for category in report["categories"]],
            ["Second", "First", "Second child", "First child"],
        )

        with self.assertRaises(ValueError):
            self.data.update_category(first["id"], "First", position=0)
        with self.assertRaises(TypeError):
            self.data.update_category(first["id"], "First", position="1")

    def test_currency_setting_is_validated_and_persisted(self):
        self.assertEqual(self.data.get_currency(), "$")
        self.assertEqual(self.data.set_currency(" € "), "€")

        self.data.close()
        self.data = Data(self.database_path)
        self.assertEqual(self.data.get_currency(), "€")

        with self.assertRaises(ValueError):
            self.data.set_currency(" ")
        with self.assertRaises(ValueError):
            self.data.set_currency("US\nD")
        with self.assertRaises(TypeError):
            self.data.set_currency(123)

    def test_period_crud_and_date_validation(self):
        start = datetime(2026, 10, 1)
        end = datetime(2026, 10, 31, 23, 59, 59)
        period = self.data.create_period(start, end)

        self.assertEqual(self.data.get_period(period["id"]), period)
        self.assertEqual(self.data.list_periods(), [period])
        self.assertEqual(
            self.data.update_period(period["id"], start, datetime(2026, 11, 1)),
            {
                "id": period["id"],
                "name": "October 2026",
                "start_date": start,
                "end_date": datetime(2026, 11, 1),
            },
        )
        with self.assertRaises(ValueError):
            self.data.create_period(end, start)
        with self.assertRaises(ValueError):
            self.data.update_period(period["id"], end, start)

        self.data.delete_period(period["id"])
        self.assertEqual(self.data.list_periods(), [])
        with self.assertRaises(LookupError):
            self.data.get_period(period["id"])

    def test_open_periods_are_named_and_closed_when_the_next_period_starts(self):
        first_start = datetime(2026, 10, 27)
        first = self.data.create_period(first_start)
        self.assertEqual(first["name"], "October 2026")
        self.assertIsNone(first["end_date"])
        self.assertEqual(
            self.data.get_period_for_date(datetime(2030, 1, 1)),
            first,
        )

        next_start = datetime(2026, 11, 26)
        second = self.data.create_period(next_start, name="November payday")
        self.assertEqual(second["name"], "November payday")
        self.assertEqual(
            self.data.get_period(first["id"])["end_date"],
            next_start - timedelta(microseconds=1),
        )
        self.assertEqual(
            self.data.get_period_for_date(datetime(2026, 11, 25)),
            self.data.get_period(first["id"]),
        )
        self.assertEqual(
            self.data.get_period_for_date(next_start),
            second,
        )

    def test_periods_can_overlap_and_names_are_validated(self):
        first = self.data.create_period(
            datetime(2026, 10, 1), datetime(2026, 10, 31, 23, 59, 59)
        )
        overlap = self.data.create_period(
            datetime(2026, 10, 15), datetime(2026, 11, 5)
        )
        self.assertEqual(
            [period["id"] for period in self.data.list_periods()],
            [first["id"], overlap["id"]],
        )
        with self.assertRaises(ValueError):
            self.data.create_period(datetime(2026, 11, 1), name="  ")

    def test_earlier_period_can_overlap_an_open_period_without_closing_it(self):
        open_period = self.data.create_period(datetime(2026, 11, 2))
        earlier_period = self.data.create_period(
            datetime(2026, 11, 1),
            datetime(2026, 11, 5, 23, 59, 59),
        )

        self.assertIsNone(self.data.get_period(open_period["id"])["end_date"])
        self.assertEqual(
            [period["id"] for period in self.data.list_periods()],
            [earlier_period["id"], open_period["id"]],
        )

    def test_period_update_allows_overlapping_another_period(self):
        first = self.data.create_period(
            datetime(2026, 10, 1), datetime(2026, 10, 10, 23, 59, 59)
        )
        second = self.data.create_period(
            datetime(2026, 10, 11), datetime(2026, 10, 20, 23, 59, 59)
        )

        updated = self.data.update_period(
            second["id"],
            datetime(2026, 10, 5),
            datetime(2026, 10, 25, 23, 59, 59),
        )
        self.assertEqual(updated["start_date"], datetime(2026, 10, 5))
        self.assertEqual(
            [period["id"] for period in self.data.list_periods()],
            [first["id"], second["id"]],
        )

    def test_open_period_balance_reports_include_later_cash_flows(self):
        period = self.data.create_period(datetime(2026, 10, 1))
        category = self.data.create_category("Salary")
        self.data.create_cash_flow(
            250_000, category["id"], datetime(2027, 1, 25), "Salary"
        )

        report = self.data.get_period_balances(period["id"])
        self.assertEqual(report["total"], 250_000)

    def test_cash_flow_crud_and_filters(self):
        groceries = self.data.create_category("Groceries")
        transport = self.data.create_category("Transport")
        first_date = datetime(2026, 10, 1)
        last_date = datetime(2026, 10, 31, 23, 59, 59)
        first = self.data.create_cash_flow(
            -2500, groceries["id"], first_date, "Groceries"
        )
        second = self.data.create_cash_flow(
            3000, groceries["id"], datetime(2026, 10, 15)
        )
        self.data.create_cash_flow(
            -500, transport["id"], last_date, "Bus"
        )

        self.assertEqual(self.data.get_cash_flow(first["id"]), first)
        self.assertEqual(len(self.data.list_cash_flows()), 3)
        self.assertEqual(
            [flow["id"] for flow in self.data.list_cash_flows(category_id=groceries["id"])],
            [first["id"], second["id"]],
        )
        self.assertEqual(
            [flow["id"] for flow in self.data.list_cash_flows(
                start_date=first_date, end_date=last_date
            )],
            [first["id"], second["id"], 3],
        )
        self.assertEqual(
            [flow["id"] for flow in self.data.list_cash_flows(
                start_date=datetime(2026, 10, 15),
                end_date=datetime(2026, 10, 15),
            )],
            [second["id"]],
        )

        updated = self.data.update_cash_flow(
            first["id"], -2800, transport["id"], datetime(2026, 10, 2), "Updated"
        )
        self.assertEqual(updated["amount"], -2800)
        self.assertEqual(updated["category_id"], transport["id"])
        self.assertEqual(updated["description"], "Updated")
        self.data.delete_cash_flow(second["id"])
        self.assertEqual(
            [flow["id"] for flow in self.data.list_cash_flows()],
            [first["id"], 3],
        )
        with self.assertRaises(LookupError):
            self.data.get_cash_flow(second["id"])

    def test_cash_flow_rejects_missing_category_and_invalid_range(self):
        with self.assertRaises(LookupError):
            self.data.create_cash_flow(-100, 999, datetime(2026, 10, 1))

        with self.assertRaises(ValueError):
            self.data.list_cash_flows(
                start_date=datetime(2026, 10, 2),
                end_date=datetime(2026, 10, 1),
            )

    def test_api_rejects_invalid_amounts_and_dates(self):
        category = self.data.create_category("Food")
        with self.assertRaises(TypeError):
            self.data.create_cash_flow(1.5, category["id"], datetime(2026, 10, 1))
        with self.assertRaises(TypeError):
            self.data.create_cash_flow(100, category["id"], "2026-10-01")
        with self.assertRaises(TypeError):
            self.data.create_period("2026-10-01", datetime(2026, 10, 31))
        with self.assertRaises(TypeError):
            self.data.create_category(123)

    def test_period_balances_include_zero_categories_and_period_boundaries(self):
        period = self.data.create_period(
            datetime(2026, 10, 1), datetime(2026, 10, 31)
        )
        food = self.data.create_category("Food")
        housing = self.data.create_category("Housing")
        utilities = self.data.create_category("Utilities")

        self.data.create_cash_flow(
            -200, food["id"], datetime(2026, 10, 1), "First day"
        )
        self.data.create_cash_flow(
            50, food["id"], datetime(2026, 10, 31), "Last day"
        )
        self.data.create_cash_flow(
            -1000, housing["id"], datetime(2026, 10, 15), "Rent"
        )
        self.data.create_cash_flow(
            5000, food["id"], datetime(2026, 11, 1), "Outside period"
        )

        report = self.data.get_period_balances(period["id"])
        self.assertEqual(
            report,
            {
                "period": period,
                "categories": [
                    {
                        "category_id": food["id"],
                        "category_name": "Food",
                        "parent_id": None,
                        "is_parent": False,
                        "balance": -150,
                    },
                    {
                        "category_id": housing["id"],
                        "category_name": "Housing",
                        "parent_id": None,
                        "is_parent": False,
                        "balance": -1000,
                    },
                    {
                        "category_id": utilities["id"],
                        "category_name": "Utilities",
                        "parent_id": None,
                        "is_parent": False,
                        "balance": 0,
                    },
                ],
                "total": -1150,
            },
        )

    def test_period_balances_roll_up_children_without_double_counting(self):
        period = self.data.create_period(
            datetime(2026, 10, 1), datetime(2026, 10, 31)
        )
        essentials = self.data.create_category("Essentials")
        groceries = self.data.create_category("Groceries", essentials["id"])
        mortgage = self.data.create_category("Mortgage", essentials["id"])
        other = self.data.create_category("Travel")
        self.data.create_cash_flow(-2500, essentials["id"], datetime(2026, 10, 2))
        self.data.create_cash_flow(-12000, groceries["id"], datetime(2026, 10, 3))
        self.data.create_cash_flow(-80000, mortgage["id"], datetime(2026, 10, 4))
        self.data.create_cash_flow(-1000, other["id"], datetime(2026, 10, 5))

        report = self.data.get_period_balances(period["id"])
        self.assertEqual(
            report["categories"],
            [
                {
                    "category_id": essentials["id"],
                    "category_name": "Essentials",
                    "parent_id": None,
                    "is_parent": True,
                    "balance": -94_500,
                },
                {
                    "category_id": groceries["id"],
                    "category_name": "Groceries",
                    "parent_id": essentials["id"],
                    "is_parent": False,
                    "balance": -12_000,
                },
                {
                    "category_id": mortgage["id"],
                    "category_name": "Mortgage",
                    "parent_id": essentials["id"],
                    "is_parent": False,
                    "balance": -80_000,
                },
                {
                    "category_id": other["id"],
                    "category_name": "Travel",
                    "parent_id": None,
                    "is_parent": False,
                    "balance": -1_000,
                },
            ],
        )
        self.assertEqual(report["total"], -95_500)

    def test_period_report_rejects_missing_period(self):
        with self.assertRaises(LookupError):
            self.data.get_period_balances(999)

    def test_cash_flows_prevent_deleting_their_category(self):
        category = self.data.create_category("Food")
        self.data.create_cash_flow(-100, category["id"], datetime(2026, 10, 1))

        with self.assertRaises(IntegrityError):
            self.data.delete_category(category["id"])

        self.assertEqual(self.data.get_category(category["id"]), category)

    def test_records_persist_after_reopening(self):
        category = self.data.create_category("Housing")
        period = self.data.create_period(datetime(2026, 10, 1), datetime(2026, 10, 31))
        flow = self.data.create_cash_flow(
            -100, category["id"], datetime(2026, 10, 5), "Rent"
        )
        budget = self.data.create_budget(500, category["id"], period["id"])

        self.data.close()
        self.data = Data(self.database_path)

        self.assertEqual(self.data.get_category(category["id"]), category)
        self.assertEqual(self.data.get_period(period["id"]), period)
        self.assertEqual(self.data.get_cash_flow(flow["id"]), flow)
        self.assertEqual(self.data.get_budget(budget["id"]), budget)
        self.assertEqual(self.data.get_period_balances(period["id"])["total"], -100)
        self.assertEqual(
            self.data.get_period_budget_report(period["id"])["total_remaining"],
            400,
        )

    def test_budget_crud_filtering_and_validation(self):
        food = self.data.create_category("Food")
        transport = self.data.create_category("Transport")
        october = self.data.create_period(
            datetime(2026, 10, 1), datetime(2026, 10, 31)
        )
        november = self.data.create_period(
            datetime(2026, 11, 1), datetime(2026, 11, 30)
        )

        budget = self.data.create_budget(50_000, food["id"], october["id"])
        other_budget = self.data.create_budget(10_000, food["id"], november["id"])
        self.assertEqual(self.data.get_budget(budget["id"]), budget)
        self.assertEqual(self.data.list_budgets(), [budget, other_budget])
        self.assertEqual(
            self.data.list_budgets(period_id=october["id"]),
            [budget],
        )
        self.assertEqual(
            self.data.list_budgets(category_id=food["id"]),
            [budget, other_budget],
        )

        with self.assertRaises(IntegrityError):
            self.data.create_budget(1, food["id"], october["id"])
        with self.assertRaises(ValueError):
            self.data.create_budget(-1, transport["id"], october["id"])
        with self.assertRaises(TypeError):
            self.data.create_budget(True, transport["id"], october["id"])
        with self.assertRaises(LookupError):
            self.data.create_budget(1, 999, october["id"])
        with self.assertRaises(LookupError):
            self.data.create_budget(1, food["id"], 999)

        updated = self.data.update_budget(
            budget["id"], 75_000, transport["id"], october["id"]
        )
        self.assertEqual(
            updated,
            {
                "id": budget["id"],
                "amount": 75_000,
                "category_id": transport["id"],
                "period_id": october["id"],
            },
        )
        with self.assertRaises(IntegrityError):
            self.data.update_budget(
                other_budget["id"], 1, transport["id"], october["id"]
            )
        self.assertEqual(self.data.get_budget(other_budget["id"]), other_budget)

        self.data.delete_budget(updated["id"])
        self.assertEqual(self.data.list_budgets(period_id=october["id"]), [])
        with self.assertRaises(LookupError):
            self.data.get_budget(updated["id"])

    def test_budget_remaining_report_uses_signed_period_balances(self):
        period = self.data.create_period(
            datetime(2026, 10, 1), datetime(2026, 10, 31)
        )
        food = self.data.create_category("Food")
        transport = self.data.create_category("Transport")
        unbudgeted = self.data.create_category("Unbudgeted")
        self.data.create_budget(5_000, food["id"], period["id"])
        self.data.create_budget(1_000, transport["id"], period["id"])

        self.data.create_cash_flow(-1_200, food["id"], datetime(2026, 10, 5))
        self.data.create_cash_flow(200, food["id"], datetime(2026, 10, 8))
        self.data.create_cash_flow(-1_500, transport["id"], datetime(2026, 10, 9))
        self.data.create_cash_flow(-700, unbudgeted["id"], datetime(2026, 10, 9))
        self.data.create_cash_flow(-10_000, food["id"], datetime(2026, 11, 1))

        report = self.data.get_period_budget_report(period["id"])
        self.assertEqual(
            report,
            {
                "period": period,
                "categories": [
                    {
                        "category_id": food["id"],
                        "category_name": "Food",
                        "budget": 5_000,
                        "balance": -1_000,
                        "remaining": 4_000,
                    },
                    {
                        "category_id": transport["id"],
                        "category_name": "Transport",
                        "budget": 1_000,
                        "balance": -1_500,
                        "remaining": -500,
                    },
                ],
                "total_budget": 6_000,
                "total_balance": -2_500,
                "total_remaining": 3_500,
            },
        )

    def test_budget_report_includes_unused_budget_and_rejects_missing_period(self):
        period = self.data.create_period(
            datetime(2026, 10, 1), datetime(2026, 10, 31)
        )
        category = self.data.create_category("Savings")
        self.data.create_budget(2_000, category["id"], period["id"])

        self.assertEqual(
            self.data.get_period_budget_report(period["id"])["categories"],
            [
                {
                    "category_id": category["id"],
                    "category_name": "Savings",
                    "budget": 2_000,
                    "balance": 0,
                    "remaining": 2_000,
                }
            ],
        )
        with self.assertRaises(LookupError):
            self.data.get_period_budget_report(999)

    def test_database_enforces_budget_amount_and_references(self):
        category = self.data.create_category("Food")
        period = self.data.create_period(
            datetime(2026, 10, 1), datetime(2026, 10, 31)
        )
        self.data.create_budget(1_000, category["id"], period["id"])

        with self.assertRaises(IntegrityError):
            with self.data.session_factory.begin() as session:
                session.add(
                    Budget(
                        amount=-1,
                        category_id=category["id"],
                        period_id=period["id"],
                    )
                )
        with self.assertRaises(IntegrityError):
            self.data.delete_category(category["id"])
        with self.assertRaises(IntegrityError):
            self.data.delete_period(period["id"])

    def test_failed_transaction_does_not_persist_changes(self):
        with self.assertRaises(RuntimeError):
            with self.data.session_factory.begin() as session:
                session.add(Category(name="Temporary"))
                raise RuntimeError("abort transaction")

        self.assertEqual(self.data.list_categories(), [])
