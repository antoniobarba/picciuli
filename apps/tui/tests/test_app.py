from __future__ import annotations

import datetime as dt
from typing import Any, cast

from conftest import TODAY, run_app
from textual import events
from textual.pilot import Pilot
from textual.widgets import Input, Select

from picciuli import (
    Account,
    AccountSplit,
    AccountType,
    Book,
    Category,
    ExternalSplit,
    TransactionKind,
)
from picciuli_tui.app import PicciuliApp
from picciuli_tui.formatting import MoneyFormat
from picciuli_tui.forms import EntryKind
from picciuli_tui.screens.accounts import AccountsScreen, RegisterScreen
from picciuli_tui.screens.budgets import BudgetsScreen
from picciuli_tui.screens.categories import CategoriesScreen
from picciuli_tui.screens.modals import (
    ConfirmScreen,
    FormScreen,
    HelpScreen,
    SplitLineRow,
    TransactionForm,
)
from picciuli_tui.screens.overview import OverviewScreen
from picciuli_tui.screens.periods import PeriodsScreen
from picciuli_tui.widgets import CalendarWidget, ListTable, ScreenTabs


def messages(app: PicciuliApp) -> list[str]:
    return [notification.message for notification in app._notifications]


async def fill(pilot: Pilot[None], **values: object) -> None:
    for name, value in values.items():
        widget = pilot.app.screen.query_one(f"#field-{name}")
        cast(Any, widget).value = value
    await pilot.pause()


async def press(pilot: Pilot[None], *keys: str) -> None:
    await pilot.press(*keys)
    await pilot.pause()


def table(app: PicciuliApp) -> ListTable:
    return app.screen.query_one(ListTable)


async def select_row(pilot: Pilot[None], row: int) -> None:
    table(cast(PicciuliApp, pilot.app)).move_cursor(row=row)
    await pilot.pause()


# Overview


def test_calendar_navigation(book: Book, checking: Account, savings: Account) -> None:
    book.transactions.record_expense(dt.date(2025, 3, 11), 4500, account_id=checking.id)
    book.transactions.record_transfer(
        dt.date(2025, 3, 13), 100, from_account_id=checking.id, to_account_id=savings.id
    )
    march = book.periods.create(dt.date(2025, 2, 27))
    holiday = book.periods.create(
        dt.date(2025, 3, 10), end=dt.date(2025, 3, 14), name="Holiday"
    )

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        screen = cast(OverviewScreen, app.screen)
        calendar = screen.query_one(CalendarWidget)
        assert screen.selected_day == TODAY
        assert screen.period_id == holiday.id
        rendered = str(calendar.render())
        assert "March 2025" in rendered and "-45" in rendered and "↔" in rendered
        await press(pilot, "left")
        assert screen.selected_day == dt.date(2025, 3, 11)
        assert table(app).row_count == 1
        await press(pilot, "right", "right", "down")
        assert screen.selected_day == dt.date(2025, 3, 20)
        assert screen.period_id == march.id
        await press(pilot, "up", "pagedown")
        assert screen.selected_day == dt.date(2025, 4, 13)
        await press(pilot, "pageup", "t")
        assert screen.selected_day == TODAY
        assert screen.period_id == march.id
        await press(pilot, "right_square_bracket")
        assert screen.period_id == holiday.id
        await press(pilot, "left_square_bracket")
        assert screen.period_id == march.id
        await press(pilot, "right_square_bracket", "down", "left_square_bracket")
        assert screen.period_id == march.id
        assert "No other period covers this day." in messages(app)

        geometry = calendar.geometry()
        pad = geometry.pad
        await pilot.click(calendar, offset=geometry.cell_origin(0, 0))
        await pilot.pause()
        assert screen.selected_day == dt.date(2025, 2, 24)
        await pilot.click(calendar, offset=(pad, 0))
        await pilot.pause()
        assert screen.selected_day == dt.date(2025, 1, 24)
        await pilot.click(calendar, offset=(pad + geometry.width - 1, 0))
        await pilot.pause()
        assert screen.selected_day == dt.date(2025, 2, 24)
        await pilot.click(calendar, offset=(pad + 10, 0))
        await pilot.click(calendar, offset=(pad + 1, 1))
        await pilot.click(calendar, offset=(pad, geometry.TOP))
        await pilot.pause()
        assert screen.selected_day == dt.date(2025, 2, 24)
        calendar.post_message(
            events.MouseScrollDown(calendar, 1, 1, 0, 1, 0, False, False, False)
        )
        await pilot.pause()
        assert screen.selected_day == dt.date(2025, 3, 24)
        calendar.post_message(
            events.MouseScrollUp(calendar, 1, 1, 0, -1, 0, False, False, False)
        )
        await pilot.pause()
        assert screen.selected_day == dt.date(2025, 2, 24)

        await press(pilot, "tab")
        assert not calendar.has_focus
        await pilot.resize_terminal(48, 60)
        await pilot.pause()
        narrow = str(calendar.render())
        assert "Mo" in narrow

    run_app(book, scenario)


def test_narrow_calendar_uses_markers(book: Book, checking: Account) -> None:
    book.transactions.record_expense(TODAY, 100, account_id=checking.id)

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        calendar = app.screen.query_one(CalendarWidget)
        text = str(calendar.render())
        assert "•" in text and "Mo" in text and "Tue" not in text
        assert calendar.geometry().cell_width == CalendarWidget.MIN_CELL

    run_app(book, scenario, size=(32, 50))


def test_selected_day_has_a_heavy_border(book: Book) -> None:
    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        calendar = app.screen.query_one(CalendarWidget)
        lines = str(calendar.render()).splitlines()
        geometry = calendar.geometry()
        # 12 March 2025 is the Wednesday of the third week.
        x, y = geometry.cell_origin(2, 2)
        assert lines[y][x - 1] == "┃" and lines[y][x + geometry.cell_width] == "┃"
        assert lines[y - 1][x - 1] == "╆" and lines[y - 1][x] == "━"
        assert lines[y + geometry.cell_height][x + geometry.cell_width] == "╃"
        assert lines[geometry.TOP - 1].startswith(" " * geometry.pad + "┌")
        assert sum(line.count("┃") for line in lines) == 2 * geometry.cell_height
        assert calendar.day_at(x, y) == TODAY
        assert calendar.day_at(x - 1, y) is None
        assert calendar.day_at(x, y + geometry.cell_height) is None
        assert calendar.day_at(x, geometry.height + 5) is None

    run_app(book, scenario)


def test_screen_tabs(book: Book) -> None:
    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        tabs = app.screen.query_one(ScreenTabs)
        assert tabs.active == "overview"
        await pilot.click("#budgets")
        await pilot.pause()
        assert isinstance(app.screen, BudgetsScreen)
        assert app.screen.query_one(ScreenTabs).active == "budgets"
        await pilot.click("#budgets")
        await pilot.pause()
        assert isinstance(app.screen, BudgetsScreen)
        await press(pilot, "3")
        assert app.screen.query_one(ScreenTabs).active == "categories"
        await pilot.click("#overview")
        await pilot.pause()
        assert isinstance(app.screen, OverviewScreen)
        # The tabs never take the focus: arrows keep moving the calendar.
        assert app.screen.query_one(CalendarWidget).has_focus
        await press(pilot, "left")
        assert cast(OverviewScreen, app.screen).selected_day == TODAY - dt.timedelta(1)

    run_app(book, scenario)


def test_overview_without_accounts_or_periods(book: Book) -> None:
    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "n")
        assert isinstance(app.screen, OverviewScreen)
        assert "Create an account first: press 2, then n." in messages(app)
        await press(pilot, "e", "d")
        assert messages(app).count("No transaction selected on this day.") == 2

    run_app(book, scenario)


def test_transaction_lifecycle(
    book: Book, checking: Account, savings: Account, food: Category
) -> None:
    book.periods.create(dt.date(2025, 2, 27))
    book.budgets.create(food.id, book.periods.list()[0].id, 10000)

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "n")
        form = app.screen
        assert isinstance(form, TransactionForm)
        await press(pilot, *"12.5")
        form.query_one("#category", Select).value = food.id
        form.query_one("#description", Input).value = "Lunch"
        await press(pilot, "ctrl+s")
        assert isinstance(app.screen, OverviewScreen)
        (transaction,) = book.transactions.list()
        assert transaction.net_amount == -1250
        assert table(app).row_count == 1

        await press(pilot, "e")
        assert isinstance(app.screen, TransactionForm)
        app.screen.query_one("#amount", Input).value = "13"
        await press(pilot, "enter")
        assert book.transactions.get(transaction.id).net_amount == -1300

        await press(pilot, "e")
        form = app.screen
        assert isinstance(form, TransactionForm)
        form.query_one("#kind", Select).value = EntryKind.TRANSFER
        form.query_one("#to-account", Select).value = savings.id
        await press(pilot, "ctrl+s")
        assert book.transactions.get(transaction.id).kind is TransactionKind.TRANSFER

        await press(pilot, "e")
        form = app.screen
        assert isinstance(form, TransactionForm)
        form.query_one("#kind", Select).value = EntryKind.SPLIT
        await pilot.pause()
        assert len(form.query(SplitLineRow)) == 2
        assert "Balanced" in str(form.query_one("#difference").render())
        await press(pilot, "ctrl+n")
        rows = form.query(SplitLineRow)
        assert len(rows) == 3
        await pilot.click(rows.last().query_one(".line-remove"))
        await pilot.pause()
        assert len(form.query(SplitLineRow)) == 2
        form.query(".line-amount").first(Input).value = "-1"
        await press(pilot, "ctrl+s")
        assert isinstance(app.screen, TransactionForm)
        assert "Off by" in str(form.query_one("#difference").render())
        await pilot.click("#cancel")
        await pilot.pause()
        assert isinstance(app.screen, OverviewScreen)

        await press(pilot, "e", "ctrl+n")
        assert app.screen.query_one("#kind", Select).value is EntryKind.SPLIT
        await pilot.click("#add-line")
        await pilot.pause()
        assert len(app.screen.query(SplitLineRow)) == 3
        await pilot.click("#save")
        await pilot.pause()
        assert isinstance(app.screen, OverviewScreen)
        assert len(book.transactions.list()[0].splits) == 2

        await press(pilot, "tab", "enter")
        assert isinstance(app.screen, TransactionForm)
        await press(pilot, "escape", "d")
        assert isinstance(app.screen, ConfirmScreen)
        await press(pilot, "n")
        assert book.transactions.list()
        await press(pilot, "d", "y")
        assert not book.transactions.list()
        assert table(app).row_count == 0

    run_app(book, scenario)


def test_go_to_and_start_period(book: Book) -> None:
    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        screen = cast(OverviewScreen, app.screen)
        await press(pilot, "g")
        await fill(pilot, date="nonsense")
        await press(pilot, "ctrl+s")
        assert isinstance(app.screen, FormScreen)
        await fill(pilot, date="2025-01-05")
        await pilot.click("#save")
        await pilot.pause()
        assert screen.selected_day == dt.date(2025, 1, 5)
        await press(pilot, "p")
        await press(pilot, "ctrl+s")
        (period,) = book.periods.list()
        assert (period.name, period.start, period.end) == (
            "January 2025",
            dt.date(2025, 1, 5),
            None,
        )
        assert screen.period_id == period.id
        await press(pilot, "g", "escape")
        assert isinstance(app.screen, OverviewScreen)

    run_app(book, scenario)


# Application


def test_modes_help_settings_and_quit(book: Book) -> None:
    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        for key, kind in (
            ("2", AccountsScreen),
            ("3", CategoriesScreen),
            ("4", PeriodsScreen),
            ("5", BudgetsScreen),
            ("1", OverviewScreen),
        ):
            await press(pilot, key)
            assert isinstance(app.screen, kind)
        await press(pilot, "question_mark")
        assert isinstance(app.screen, HelpScreen)
        await press(pilot, "2")
        assert isinstance(app.screen, HelpScreen)
        await press(pilot, "escape", "s")
        await fill(pilot, currency="€", digits="x")
        await press(pilot, "ctrl+s")
        assert isinstance(app.screen, FormScreen)
        await fill(pilot, digits="0")
        await press(pilot, "ctrl+s")
        assert app.money == MoneyFormat("€", 0)
        await press(pilot, "q")
        assert app.return_code == 0

    run_app(book, scenario)


# Accounts


def test_accounts_screen(book: Book) -> None:
    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "2", "n")
        await fill(pilot, name="Checking", opening_balance="100")
        await press(pilot, "ctrl+s")
        await press(pilot, "n")
        await fill(pilot, name="Card", type=AccountType.CREDIT_CARD)
        await press(pilot, "ctrl+s")
        await press(pilot, "n")
        await fill(pilot, name="Savings", goal="500", opening_balance="100")
        await press(pilot, "ctrl+s")
        assert table(app).row_count == 3
        checking, card, savings = book.accounts.list()

        await select_row(pilot, 0)
        await press(pilot, "shift+down")
        assert book.accounts.get(checking.id).position == 2
        await press(pilot, "e")
        await fill(pilot, name="Main")
        await press(pilot, "ctrl+s")
        assert book.accounts.get(checking.id).name == "Main"

        await select_row(pilot, 0)
        await press(pilot, "c", "ctrl+s")
        assert book.accounts.get(card.id).is_closed
        await press(pilot, "c", "y")
        assert not book.accounts.get(card.id).is_closed
        await press(pilot, "d", "y")
        assert [a.name for a in book.accounts.list()] == ["Main", "Savings"]

        await select_row(pilot, 0)
        await press(pilot, "c", "ctrl+s")
        assert isinstance(app.screen, FormScreen)
        await press(pilot, "escape")
        book.transactions.record_transfer(
            TODAY, 50, from_account_id=checking.id, to_account_id=savings.id
        )
        book.transactions.create(
            TODAY,
            [
                AccountSplit(checking.id, -300),
                AccountSplit(savings.id, 200),
                ExternalSplit(-100),
            ],
            description="Mixed",
        )
        await press(pilot, "d", "y")
        assert any("close it instead" in message for message in messages(app))

        await press(pilot, "enter")
        register = app.screen
        assert isinstance(register, RegisterScreen)
        assert table(app).row_count == 2
        assert table(app).cursor_row == 1
        await press(pilot, "n")
        form = app.screen
        assert isinstance(form, TransactionForm)
        assert form.query_one("#account", Select).value == checking.id
        await press(pilot, "escape", "e")
        assert isinstance(app.screen, TransactionForm)
        await press(pilot, "escape")
        await select_row(pilot, 0)
        await press(pilot, "enter", "escape", "d", "y")
        assert len(book.transactions.list()) == 1
        await press(pilot, "escape")
        assert isinstance(app.screen, AccountsScreen)

    run_app(book, scenario)


def test_register_of_closed_account(book: Book) -> None:
    account = book.accounts.create("Old", AccountType.CASH)
    book.accounts.close(account.id, on=TODAY)

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "2", "enter")
        assert isinstance(app.screen, RegisterScreen)
        assert "closed" in str(app.screen.query_one("#register-title").render())
        await press(pilot, "e", "d")
        assert isinstance(app.screen, RegisterScreen)

    run_app(book, scenario)


def test_empty_lists_ignore_actions(book: Book) -> None:
    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        for mode in ("2", "3", "4"):
            await press(pilot, mode, "e", "d", "shift+up")
            assert not isinstance(app.screen, (FormScreen, ConfirmScreen))
        await press(pilot, "2", "c")
        assert isinstance(app.screen, AccountsScreen)

    run_app(book, scenario)


# Categories


def test_categories_screen(book: Book, checking: Account) -> None:
    food = book.categories.create("Food")
    home = book.categories.create("Home")
    groceries = book.categories.create("Groceries", parent_id=food.id)
    book.transactions.record_expense(
        TODAY, 100, account_id=checking.id, category_id=home.id
    )

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "3")
        assert table(app).row_count == 3
        await press(pilot, "n")
        await fill(pilot, name="Transport")
        await press(pilot, "ctrl+s")
        transport = next(c for c in book.categories.list() if c.name == "Transport")
        assert transport.parent_id is None
        await select_row(pilot, 1)
        await press(pilot, "n")
        await fill(pilot, name="Fruit")
        await press(pilot, "ctrl+s")
        fruit = next(c for c in book.categories.list() if c.name == "Fruit")
        assert fruit.parent_id == food.id

        await select_row(pilot, 0)
        await press(pilot, "enter")
        await fill(pilot, symbol="FD")
        await press(pilot, "ctrl+s")
        assert book.categories.get(food.id).symbol == "FD"
        await press(pilot, "shift+down")
        assert book.categories.get(food.id).position == 2
        await press(pilot, "d")
        assert "Delete or move its subcategories first." in messages(app)

        rows = [c.id for c in book.categories.list()]
        await select_row(pilot, rows.index(transport.id))
        await press(pilot, "d", "y")
        assert transport.id not in {c.id for c in book.categories.list()}

        rows = [c.id for c in book.categories.list()]
        await select_row(pilot, rows.index(home.id))
        await press(pilot, "d")
        await fill(pilot, target=groceries.id)
        await press(pilot, "ctrl+s")
        (expense,) = book.transactions.list()
        assert expense.external_splits[0].category_id == groceries.id

    run_app(book, scenario)


# Periods and budgets


def test_periods_screen(book: Book) -> None:
    book.periods.create(dt.date(2025, 1, 1), end=dt.date(2025, 1, 31))
    current = book.periods.create(dt.date(2025, 2, 27))

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "4")
        assert table(app).cursor_row == 1
        await press(pilot, "n")
        await fill(pilot, start="2025-03-01", end="2025-03-31")
        await press(pilot, "ctrl+s")
        assert [p.name for p in book.periods.list()][-1] == "March 2025"
        await select_row(pilot, 1)
        await press(pilot, "enter")
        await fill(pilot, name="Pay cycle")
        await press(pilot, "ctrl+s")
        assert book.periods.get(current.id).name == "Pay cycle"
        await press(pilot, "d", "y")
        assert len(book.periods.list()) == 2

    run_app(book, scenario)


def test_budgets_screen(book: Book, checking: Account, food: Category) -> None:
    home = book.categories.create("Home")
    january = book.periods.create(dt.date(2025, 1, 1))
    february = book.periods.create(dt.date(2025, 2, 1))
    book.budgets.create(food.id, january.id, 30000)
    book.transactions.record_expense(
        dt.date(2025, 3, 2), 45000, account_id=checking.id, category_id=food.id
    )

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "5")
        screen = cast(BudgetsScreen, app.screen)
        assert screen.period_id == february.id
        await press(pilot, "y", "ctrl+s")
        assert len(book.budgets.list(period_id=february.id)) == 1
        assert table(app).row_count == 1
        await press(pilot, "n")
        await fill(pilot, category=home.id, amount="")
        await press(pilot, "ctrl+s")
        assert isinstance(app.screen, FormScreen)
        await fill(pilot, amount="50")
        await press(pilot, "ctrl+s")
        assert len(book.budgets.list(period_id=february.id)) == 2
        await select_row(pilot, 0)
        await press(pilot, "enter")
        await fill(pilot, amount="400")
        await press(pilot, "ctrl+s")
        assert {b.amount for b in book.budgets.list(period_id=february.id)} == {
            40000,
            5000,
        }
        await press(pilot, "d", "y")
        assert len(book.budgets.list(period_id=february.id)) == 1
        await press(pilot, "left_square_bracket")
        assert screen.period_id == january.id
        await press(pilot, "left_square_bracket")
        assert screen.period_id == january.id
        await press(pilot, "right_square_bracket")
        assert screen.period_id == february.id

    run_app(book, scenario)


def test_budgets_without_periods_or_categories(book: Book) -> None:
    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "5", "n", "y", "e", "left_square_bracket")
        assert "Create a period first: press 4, then n." in messages(app)
        assert "There is no other period to copy from." in messages(app)
        book.periods.create(TODAY)
        await press(pilot, "1", "5", "n")
        assert "Create a category first: press 3, then n." in messages(app)

    run_app(book, scenario)
