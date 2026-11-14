"""The Textual application."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any, ClassVar

from textual.app import App
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen, Screen

from picciuli import Book, PicciuliError
from picciuli_tui.formatting import MoneyFormat
from picciuli_tui.forms import InputError, save_settings
from picciuli_tui.screens.accounts import AccountsScreen
from picciuli_tui.screens.base import BookScreen
from picciuli_tui.screens.budgets import BudgetsScreen
from picciuli_tui.screens.categories import CategoriesScreen
from picciuli_tui.screens.modals import FormScreen, FormValues, HelpScreen, TextField
from picciuli_tui.screens.overview import OverviewScreen
from picciuli_tui.screens.periods import PeriodsScreen

GLOBAL_ACTIONS = {"switch_mode", "settings", "help", "quit"}


class PicciuliApp(App[None]):
    """Console interface to a Picciuli book."""

    CSS_PATH = "app.tcss"
    TITLE = "Picciuli"

    MODES: ClassVar[dict[str, str | Callable[[], Screen[Any]]]] = {
        "overview": OverviewScreen,
        "accounts": AccountsScreen,
        "categories": CategoriesScreen,
        "periods": PeriodsScreen,
        "budgets": BudgetsScreen,
    }

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("1", "switch_mode('overview')", "Overview", show=False),
        Binding("2", "switch_mode('accounts')", "Accounts", show=False),
        Binding("3", "switch_mode('categories')", "Categories", show=False),
        Binding("4", "switch_mode('periods')", "Periods", show=False),
        Binding("5", "switch_mode('budgets')", "Budgets", show=False),
        Binding("s", "settings", "Settings"),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        book: Book,
        *,
        name: str | None = None,
        today: Callable[[], dt.date] = dt.date.today,
    ) -> None:
        """Create the application for an open book.

        Args:
            book: The book to show; the caller keeps ownership and closes it.
            name: File name shown in the header.
            today: Clock used for "today" (replaceable in tests).
        """
        super().__init__()
        self.HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (110, "-wide")]
        self.book = book
        self.today = today
        self.money = MoneyFormat.from_settings(book.settings.get())
        if name:
            self.title = f"Picciuli · {name}"

    def on_mount(self) -> None:
        """Start on the overview."""
        self.switch_mode("overview")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Disable global keys while a dialog is open."""
        return not (action in GLOBAL_ACTIONS and isinstance(self.screen, ModalScreen))

    def attempt(self, operation: Callable[[], Any]) -> bool:
        """Run a library call; show expected errors as notifications.

        Returns:
            Whether the call succeeded.
        """
        try:
            operation()
        except (PicciuliError, InputError) as error:
            self.notify(str(error), title="Cannot do that", severity="error")
            return False
        return True

    def action_help(self) -> None:
        """Show the key reference."""
        self.push_screen(HelpScreen())

    def action_settings(self) -> None:
        """Edit the currency settings."""

        def submit(values: FormValues) -> MoneyFormat:
            return save_settings(
                self.book, currency=values["currency"], digits=values["digits"]
            )

        self.push_screen(
            FormScreen(
                "Settings",
                [
                    TextField("currency", "Currency", self.money.currency),
                    TextField("digits", "Decimal digits", str(self.money.digits)),
                ],
                submit,
                help=(
                    "Decimal digits only change how stored amounts are read: "
                    "they are never rescaled."
                ),
            ),
            self._settings_saved,
        )

    def _settings_saved(self, money: MoneyFormat | None) -> None:
        if money is not None:
            self.money = money
            if isinstance(self.screen, BookScreen):
                self.screen.reload()
