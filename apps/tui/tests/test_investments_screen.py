from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal
from typing import Any, cast

from conftest import TODAY, FakeProvider, FakeRates, run_app
from rich.console import Console
from test_app import fill, messages, press
from textual.pilot import Pilot
from textual.widgets import OptionList, Select, Static

from picciuli import Account, AccountType, Book, CostMethod, SecurityKind
from picciuli.prices import CachingProvider, register_provider, unregister_provider
from picciuli.rates import (
    CachingRateProvider,
    register_rate_provider,
    unregister_rate_provider,
)
from picciuli_tui.app import PicciuliApp
from picciuli_tui.screens.accounts import AccountsScreen, RegisterScreen
from picciuli_tui.screens.investments import (
    InvestmentsScreen,
    guess_kind,
    looks_like_isin,
)
from picciuli_tui.screens.modals import FormScreen, PickScreen
from picciuli_tui.screens.overview import OverviewScreen
from picciuli_tui.widgets import ListTable


def holdings(app: PicciuliApp) -> ListTable:
    return app.screen.query_one("#holdings", ListTable)


def securities(app: PicciuliApp) -> ListTable:
    return app.screen.query_one("#securities", ListTable)


async def settle(app: PicciuliApp, pilot: Pilot[None]) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_investments_screen(book: Book, checking: Account) -> None:
    provider = FakeProvider()
    provider.prices["VWCE.DE"] = Decimal(40)
    book.settings.update(currency_code="EUR")
    broker = book.accounts.create("Broker", AccountType.INVESTMENT)
    gains = book.categories.create("Gains")

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "6")
        assert isinstance(app.screen, InvestmentsScreen)
        assert holdings(app).row_count == 1  # the empty cash line of Broker
        await press(pilot, "b")
        assert "Create an investment account and a security first." in messages(app)
        await press(pilot, "p", "h")
        assert "Select a security first." in messages(app)
        assert "Nothing has been bought yet." in messages(app)

        await press(pilot, "f")
        await fill(pilot, query=" ")
        await press(pilot, "ctrl+s")
        await fill(pilot, query="nothing")
        await press(pilot, "ctrl+s")
        assert "nothing found for 'nothing'" in messages(app)
        await fill(pilot, query="ie00bk5bqt80")
        await press(pilot, "ctrl+s")
        assert isinstance(app.screen, PickScreen)
        app.screen.query_one(OptionList).highlighted = 0
        await press(pilot, "enter")
        form = cast(FormScreen[object], app.screen)
        assert form.values() == {
            "name": "Vanguard FTSE All-World",
            "symbol": "VWCE.DE",
            "isin": "IE00BK5BQT80",
            "currency": "EUR",
            "kind": SecurityKind.ETF,
            "notes": "",
        }
        await press(pilot, "ctrl+s")
        (etf,) = book.securities.list()

        await press(pilot, "b")
        await fill(pilot, quantity="2", amount="70", fee="1", category_id=gains.id)
        await press(pilot, "ctrl+s")
        assert book.accounts.balance(checking.id) == -7100
        assert holdings(app).row_count == 1
        assert "no price" in str(holdings(app).get_row_at(0)[3])

        await press(pilot, "r")
        await settle(app, pilot)
        assert "1 prices and 0 exchange rates updated" in messages(app)
        assert book.investments.valuation(broker.id).market_value == 8000
        assert "40.00 EUR" in str(holdings(app).get_row_at(0)[3])

        await press(pilot, "p")
        await fill(pilot, price="45")
        await press(pilot, "ctrl+s")
        latest = book.securities.latest_price(etf.id)
        assert latest is not None and latest.price == 45

        await press(pilot, "x")
        await fill(
            pilot, quantity="1", amount="50", other_account_id=0, category_id=gains.id
        )
        await press(pilot, "ctrl+s")
        assert "Realized gain: +$15.00" in messages(app)
        assert holdings(app).row_count == 2  # the holding and 50 of cash

        await press(pilot, "h")
        await settle(app, pilot)
        assert provider.history_starts == [TODAY]

        securities(app).focus()
        await press(pilot, "e")
        await fill(pilot, name="All-World")
        await press(pilot, "ctrl+s")
        assert book.securities.get(etf.id).name == "All-World"
        await press(pilot, "d", "y")
        assert any("used by transactions" in m for m in messages(app))
        await press(pilot, "n")
        await fill(pilot, name="Manual", currency="")
        await press(pilot, "ctrl+s")
        assert isinstance(app.screen, FormScreen)
        await fill(pilot, currency="usd")
        await press(pilot, "ctrl+s")
        assert securities(app).row_count == 2
        securities(app).move_cursor(row=1)
        await press(pilot, "enter")
        assert isinstance(app.screen, FormScreen)
        await press(pilot, "escape", "d", "y")
        assert securities(app).row_count == 1

        holdings(app).focus()
        await press(pilot, "x")
        assert cast(FormScreen[object], app.screen).values()["security_id"] == etf.id
        await press(pilot, "escape", "enter")
        assert isinstance(app.screen, RegisterScreen)

    run_app(book, scenario, price_provider=provider)


def test_market_values_in_accounts_and_overview(book: Book, checking: Account) -> None:
    broker = book.accounts.create("Broker", AccountType.INVESTMENT, goal=10000)
    etf = book.securities.create("ETF", currency="USD")
    book.investments.record_buy(
        TODAY,
        account_id=broker.id,
        security_id=etf.id,
        quantity=2,
        cost=7000,
        from_account_id=checking.id,
    )
    book.securities.set_price(etf.id, TODAY, Decimal(45))

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        overview = cast(OverviewScreen, app.screen)
        console = Console(width=120, file=io.StringIO(), record=True)
        console.print(overview.query_one("#period-panel", Static).content)
        panel = console.export_text()
        assert "$90.00" in panel
        await press(pilot, "2")
        assert isinstance(app.screen, AccountsScreen)
        row = app.screen.query_one(ListTable).get_row(str(broker.id))
        assert "$70.00" in str(row[2]) and "$90.00" in str(row[3])
        assert "90%" in str(row[5])
        total = str(app.screen.query_one("#accounts-total").render())
        assert "$20.00" in total and "market value" in total

    run_app(book, scenario)


def test_settings_and_live_prices(book: Book, checking: Account) -> None:
    provider = FakeProvider()
    provider.prices["E"] = Decimal(10)
    book.securities.create("ETF", currency="EUR", symbol="E")

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "s")
        select = app.screen.query_one("#field-price_provider", Select)
        assert select.value == "yahoo"
        assert "Yahoo Finance" in str(app.screen.query_one(".form-help").render())
        await fill(pilot, currency_code="eur", cost_method=CostMethod.FIFO)
        await press(pilot, "ctrl+s")
        settings = book.settings.get()
        assert (settings.currency_code, settings.cost_method) == (
            "EUR",
            CostMethod.FIFO,
        )
        await press(pilot, "6", "l")
        await settle(app, pilot)
        assert app.live
        assert "Live prices on (every 60 s)" in messages(app)
        title = str(app.screen.query_one("#holdings-title").render())
        assert "live every 60 s" in title and "updated" in title
        assert book.securities.latest_price(book.securities.list()[0].id)
        await press(pilot, "l")
        assert not app.live
        assert "Live prices off" in messages(app)
        provider.broken = True
        await press(pilot, "r")
        await settle(app, pilot)
        assert "provider exploded" in messages(app)
        provider.broken = False
        provider.prices.clear()
        await press(pilot, "r")
        await settle(app, pilot)
        assert any("unknown symbol E" in m for m in messages(app))

    run_app(book, scenario, price_provider=provider, live=False)


def test_live_from_start_and_provider_from_settings(book: Book) -> None:
    register_provider(FakeProvider)
    try:
        book.settings.update(price_provider="fake")

        async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
            await settle(app, pilot)
            assert app.live
            provider = app.price_provider()
            assert isinstance(provider, CachingProvider)
            assert provider.id == "fake" and app.price_provider() is provider
            unregister_provider("fake")
            app._provider = None
            await press(pilot, "6", "r")
            assert any("unknown price provider" in m for m in messages(app))
            title = str(app.screen.query_one("#holdings-title").render())
            assert "fake" in title

        run_app(book, scenario, live=True, refresh_seconds=30)
    finally:
        unregister_provider("fake")


def test_helpers() -> None:
    from picciuli.prices import SecurityInfo

    assert looks_like_isin(" IE00BK5BQT80 ")
    assert not looks_like_isin("VWCE.DE")
    assert guess_kind(SecurityInfo("A", "A", kind="Equity")) is SecurityKind.STOCK
    assert guess_kind(SecurityInfo("A", "A")) is SecurityKind.OTHER
    assert dt.date(2025, 3, 12) == TODAY


def test_converted_price_columns(book: Book, checking: Account) -> None:
    book.settings.update(currency_code="EUR")
    broker = book.accounts.create("Broker", AccountType.INVESTMENT)
    apple = book.securities.create("Apple", currency="USD", symbol="AAPL")
    etf = book.securities.create("ETF", currency="EUR", symbol="E")
    gbp = book.securities.create("Pounds", currency="GBP")
    book.securities.create("Unpriced", currency="USD")
    for security in (apple, etf):
        book.investments.record_buy(
            TODAY,
            account_id=broker.id,
            security_id=security.id,
            quantity=1,
            cost=10000,
            from_account_id=checking.id,
        )
    book.securities.set_price(gbp.id, TODAY, Decimal("0.5"))
    provider = FakeProvider()
    provider.prices.update({"AAPL": Decimal("356.27"), "E": Decimal("130.4")})
    provider.currencies["AAPL"] = "USD"
    rates = FakeRates()
    rates.rates["USD"] = Decimal("0.9068")

    async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
        await press(pilot, "6")
        assert holdings(app).columns[cast(Any, "converted")].label.plain == (
            "Price (EUR)"
        )
        assert "rates Fake rates" in str(
            app.screen.query_one("#holdings-title").render()
        )
        assert str(holdings(app).get_row(f"{broker.id}:{apple.id}")[4]) == ""
        await press(pilot, "r")
        await settle(app, pilot)
        assert str(holdings(app).get_row(f"{broker.id}:{apple.id}")[4]) == (
            "323.07 EUR"
        )
        assert str(holdings(app).get_row(f"{broker.id}:{etf.id}")[4]) == ("130.40 EUR")
        rows = {
            name: securities(app).get_row(str(s.id))
            for name, s in (("apple", apple), ("etf", etf), ("gbp", gbp))
        }
        assert str(rows["apple"][6]) == "323.07 EUR"
        assert str(rows["etf"][6]) == "130.40 EUR"
        assert str(rows["gbp"][6]) == "?"
        book.securities.set_exchange_rate("GBP", TODAY, Decimal("1.2"))
        book.settings.update(currency_code="USD")
        book.securities.set_exchange_rate("GBP", TODAY, Decimal("1.3"))
        cast(InvestmentsScreen, app.screen).reload()
        await pilot.pause()
        assert securities(app).columns[cast(Any, "converted")].label.plain == (
            "Price (USD)"
        )
        assert str(securities(app).get_row(str(gbp.id))[6]) == "0.65 USD"
        assert str(securities(app).get_row(str(apple.id))[6]) == "356.27 USD"

    run_app(book, scenario, price_provider=provider, rate_provider=rates)


def test_rate_provider_setting_and_cache(book: Book) -> None:
    register_rate_provider(FakeRates)
    try:

        async def scenario(app: PicciuliApp, pilot: Pilot[None]) -> None:
            await press(pilot, "s")
            select = app.screen.query_one("#field-rate_provider", Select)
            assert select.value == "yahoo"
            help_text = str(app.screen.query_one(".form-help").render())
            assert "Exchange-rate providers" in help_text and "Fake rates" in help_text
            await fill(pilot, rate_provider="fakerates")
            await press(pilot, "ctrl+s")
            assert book.settings.get().rate_provider == "fakerates"
            rates = app.rate_provider()
            assert isinstance(rates, CachingRateProvider)
            assert rates.id == "fakerates" and app.rate_provider() is rates
            unregister_rate_provider("fakerates")
            app._rate_provider = None
            await press(pilot, "s")
            options = app.screen.query_one("#field-rate_provider", Select)
            assert options.value == "fakerates"
            await press(pilot, "escape", "6")
            title = str(app.screen.query_one("#holdings-title").render())
            assert "rates fakerates" in title
            book.settings.update(currency_code="EUR")
            book.securities.create("US", currency="USD", symbol="US")
            prices = FakeProvider()
            prices.prices["US"] = Decimal(1)
            prices.currencies["US"] = "USD"
            app._fixed_provider = prices
            await press(pilot, "r")
            await settle(app, pilot)
            assert any(
                "unknown exchange-rate provider 'fakerates'" in m for m in messages(app)
            )

        run_app(book, scenario, rate_provider=None)
    finally:
        unregister_rate_provider("fakerates")
