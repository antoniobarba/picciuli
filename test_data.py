import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from data import Category, Data


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
            {"categories", "cash_flows", "periods", "budgets"},
        )
        self.assertEqual(
            {column["name"] for column in inspector.get_columns("cash_flows")},
            {"id", "amount", "description", "category_id", "occurred_at"},
        )

    def test_category_crud_and_ordering(self):
        food = self.data.create_category(" Food ")
        housing = self.data.create_category("Housing")

        self.assertEqual(food, {"id": 1, "name": "Food"})
        self.assertEqual(self.data.get_category(food["id"]), food)
        self.assertEqual(
            self.data.list_categories(),
            [food, housing],
        )
        self.assertEqual(
            self.data.update_category(food["id"], "Groceries"),
            {"id": food["id"], "name": "Groceries"},
        )

        self.data.delete_category(housing["id"])
        self.assertEqual(self.data.list_categories(), [{"id": food["id"], "name": "Groceries"}])

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
            [{"id": 1, "name": "Food"}, {"id": 2, "name": "Other"}],
        )

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
                    {"category_id": food["id"], "category_name": "Food", "balance": -150},
                    {
                        "category_id": housing["id"],
                        "category_name": "Housing",
                        "balance": -1000,
                    },
                    {
                        "category_id": utilities["id"],
                        "category_name": "Utilities",
                        "balance": 0,
                    },
                ],
                "total": -1150,
            },
        )

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

        self.data.close()
        self.data = Data(self.database_path)

        self.assertEqual(self.data.get_category(category["id"]), category)
        self.assertEqual(self.data.get_period(period["id"]), period)
        self.assertEqual(self.data.get_cash_flow(flow["id"]), flow)
        self.assertEqual(self.data.get_period_balances(period["id"])["total"], -100)

    def test_failed_transaction_does_not_persist_changes(self):
        with self.assertRaises(RuntimeError):
            with self.data.session_factory.begin() as session:
                session.add(Category(name="Temporary"))
                raise RuntimeError("abort transaction")

        self.assertEqual(self.data.list_categories(), [])
