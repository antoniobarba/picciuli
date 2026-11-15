"""The Textual application."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any, ClassVar

from textual.app import App
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen, Screen
from textual.timer import Timer

from picciuli import Book, PicciuliError, PriceUpdate
from picciuli.prices import (
    CachingProvider,
    PriceProvider,
    available_providers,
    create_provider,
)
from picciuli.rates import (
    CachingRateProvider,
    ExchangeRateProvider,
    available_rate_providers,
    create_rate_provider,
)
from picciuli_tui.formatting import COST_METHOD_LABELS, MoneyFormat
from picciuli_tui.forms import InputError, save_settings
from picciuli_tui.screens.accounts import AccountsScreen
from picciuli_tui.screens.base import BookScreen
from picciuli_tui.screens.budgets import BudgetsScreen
from picciuli_tui.screens.categories import CategoriesScreen
from picciuli_tui.screens.investments import InvestmentsScreen
from picciuli_tui.screens.modals import (
    ChoiceField,
    FormScreen,
    FormValues,
    HelpScreen,
    TextField,
)
from picciuli_tui.screens.overview import OverviewScreen
from picciuli_tui.screens.periods import PeriodsScreen

GLOBAL_ACTIONS = {"switch_mode", "settings", "help", "quit", "toggle_live"}


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
        "investments": InvestmentsScreen,
    }

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("1", "switch_mode('overview')", "Overview", show=False),
        Binding("2", "switch_mode('accounts')", "Accounts", show=False),
        Binding("3", "switch_mode('categories')", "Categories", show=False),
        Binding("4", "switch_mode('periods')", "Periods", show=False),
        Binding("5", "switch_mode('budgets')", "Budgets", show=False),
        Binding("6", "switch_mode('investments')", "Investments", show=False),
        Binding("s", "settings", "Settings"),
        Binding("l", "toggle_live", "Live prices", show=False),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        book: Book,
        *,
        name: str | None = None,
        today: Callable[[], dt.date] = dt.date.today,
        price_provider: PriceProvider | None = None,
        rate_provider: ExchangeRateProvider | None = None,
        refresh_seconds: float = 60.0,
        live: bool = False,
    ) -> None:
        """Create the application for an open book.

        Args:
            book: The book to show; the caller keeps ownership and closes it.
            name: File name shown in the header.
            today: Clock used for "today" (replaceable in tests).
            price_provider: Provider to use instead of the one selected in the
                book settings (handy for tests).
            rate_provider: Exchange-rate provider to use instead of the one
                selected in the book settings (handy for tests).
            refresh_seconds: Interval between price refreshes in live mode.
            live: Whether to start with live prices on.
        """
        super().__init__()
        self.HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (110, "-wide")]
        self.book = book
        self.today = today
        self.money = MoneyFormat.from_settings(book.settings.get())
        self.refresh_seconds = refresh_seconds
        self.last_price_update: dt.datetime | None = None
        self._start_live = live
        self._fixed_provider = price_provider
        self._provider: PriceProvider | None = None
        self._fixed_rate_provider = rate_provider
        self._rate_provider: ExchangeRateProvider | None = None
        self._live_timer: Timer | None = None
        if name:
            self.title = f"Picciuli · {name}"

    def on_mount(self) -> None:
        """Start on the overview."""
        self.switch_mode("overview")
        if self._start_live:
            self.call_after_refresh(self.set_live, True)

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

    def reload_screen(self) -> None:
        """Reload the data of the current main screen."""
        if isinstance(self.screen, BookScreen):
            self.screen.reload()

    def action_help(self) -> None:
        """Show the key reference."""
        self.push_screen(HelpScreen())

    # Settings

    def action_settings(self) -> None:
        """Edit the book settings."""
        settings = self.book.settings.get()
        providers = [(info.name, info.id) for info in available_providers()]
        if settings.price_provider not in {value for _, value in providers}:
            providers.append(
                (f"{settings.price_provider} (not installed)", settings.price_provider)
            )
        rate_providers = [(info.name, info.id) for info in available_rate_providers()]
        if settings.rate_provider not in {value for _, value in rate_providers}:
            rate_providers.append(
                (f"{settings.rate_provider} (not installed)", settings.rate_provider)
            )
        descriptions = "\n".join(
            f"• {info.name}: {info.description}" for info in available_providers()
        )
        rate_descriptions = "\n".join(
            f"• {info.name}: {info.description}" for info in available_rate_providers()
        )

        def submit(values: FormValues) -> MoneyFormat:
            return save_settings(
                self.book,
                currency=values["currency"],
                digits=values["digits"],
                currency_code=values["currency_code"],
                cost_method=values["cost_method"],
                price_provider=values["price_provider"],
                rate_provider=values["rate_provider"],
            )

        self.push_screen(
            FormScreen(
                "Settings",
                [
                    TextField("currency", "Currency", self.money.currency),
                    TextField("digits", "Decimal digits", str(self.money.digits)),
                    TextField(
                        "currency_code",
                        "Currency code",
                        settings.currency_code or "",
                        placeholder="ISO code, e.g. EUR",
                    ),
                    ChoiceField(
                        "cost_method",
                        "Cost of sales",
                        [
                            (label, method)
                            for method, label in COST_METHOD_LABELS.items()
                        ],
                        settings.cost_method,
                    ),
                    ChoiceField(
                        "price_provider",
                        "Price provider",
                        providers,
                        settings.price_provider,
                    ),
                    ChoiceField(
                        "rate_provider",
                        "Exchange rates",
                        rate_providers,
                        settings.rate_provider,
                    ),
                ],
                submit,
                help=(
                    "Decimal digits only change how stored amounts are read: "
                    "they are never rescaled. The currency code converts "
                    "securities quoted in other currencies; changing it deletes "
                    "stored exchange rates. The cost method applies to sales "
                    "recorded afterwards.\n\nPrice providers:\n"
                    + descriptions
                    + "\n\nExchange-rate providers:\n"
                    + rate_descriptions
                ),
            ),
            self._settings_saved,
        )

    def _settings_saved(self, money: MoneyFormat | None) -> None:
        if money is not None:
            self.money = money
            self.reload_screen()

    # Prices

    def price_provider(self) -> PriceProvider:
        """Return the provider selected in the settings (cached between calls).

        Raises:
            PriceProviderError: If the selected provider is not installed.
        """
        if self._fixed_provider is not None:
            return self._fixed_provider
        selected = self.book.settings.get().price_provider
        if self._provider is None or self._provider.id != selected:
            self._provider = CachingProvider(
                create_provider(selected), ttl=max(1.0, self.refresh_seconds / 2)
            )
        return self._provider

    def rate_provider(self) -> ExchangeRateProvider:
        """Return the exchange-rate provider selected in the settings (cached).

        Raises:
            PriceProviderError: If the selected provider is not installed.
        """
        if self._fixed_rate_provider is not None:
            return self._fixed_rate_provider
        selected = self.book.settings.get().rate_provider
        if self._rate_provider is None or self._rate_provider.id != selected:
            self._rate_provider = CachingRateProvider(
                create_rate_provider(selected), ttl=max(1.0, self.refresh_seconds / 2)
            )
        return self._rate_provider

    @property
    def live(self) -> bool:
        """Whether prices are refreshed periodically."""
        return self._live_timer is not None

    def refresh_prices(
        self, *, history_start: dt.date | None = None, quiet: bool = False
    ) -> None:
        """Download prices in a background thread, then reload the screen.

        Args:
            history_start: Also download daily prices since this day.
            quiet: Do not announce successful refreshes (live mode).
        """
        try:
            provider = self.price_provider()
        except PicciuliError as error:
            self.notify(str(error), title="Cannot refresh prices", severity="error")
            return
        rates: ExchangeRateProvider | None
        try:
            rates = self.rate_provider()
        except PicciuliError:
            rates = None  # the library reports the missing provider

        def work() -> None:
            try:
                update = self.book.investments.refresh_prices(
                    provider, rate_provider=rates, history_start=history_start
                )
            except PicciuliError as error:
                self.call_from_thread(
                    self.notify,
                    str(error),
                    title="Cannot refresh prices",
                    severity="error",
                )
                return
            self.call_from_thread(self._prices_refreshed, update, quiet)

        self.run_worker(work, thread=True, group="prices", exit_on_error=False)

    def _prices_refreshed(self, update: PriceUpdate, quiet: bool) -> None:
        self.last_price_update = dt.datetime.now()
        if update.errors:
            self.notify(
                "\n".join(update.errors),
                title="Some prices were not updated",
                severity="warning",
            )
        elif not quiet:
            self.notify(
                f"{len(update.prices)} prices and "
                f"{len(update.exchange_rates)} exchange rates updated",
                title="Prices",
            )
        self.reload_screen()

    def set_live(self, on: bool) -> None:
        """Turn the periodic price refresh on or off."""
        if on and self._live_timer is None:
            self.refresh_prices(quiet=True)
            self._live_timer = self.set_interval(
                self.refresh_seconds, lambda: self.refresh_prices(quiet=True)
            )
        elif not on and self._live_timer is not None:
            self._live_timer.stop()
            self._live_timer = None
        self.reload_screen()

    def action_toggle_live(self) -> None:
        """Turn live prices on or off."""
        self.set_live(not self.live)
        state = f"on (every {self.refresh_seconds:g} s)" if self.live else "off"
        self.notify(f"Live prices {state}", title="Prices")
