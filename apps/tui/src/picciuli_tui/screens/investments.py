"""Investments: holdings at market value, securities and their prices."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Footer, Static

from picciuli import (
    AccountValuation,
    PicciuliError,
    Price,
    Security,
    SecurityKind,
    Transaction,
)
from picciuli.prices import SecurityInfo
from picciuli_tui.formatting import (
    SECURITY_KIND_LABELS,
    percent_text,
    price_text,
    quantity_text,
    rounded_price,
    short_date,
)
from picciuli_tui.forms import (
    InputError,
    SecurityDraft,
    optional_text,
    save_price,
    save_security,
)
from picciuli_tui.screens.accounts import RegisterScreen
from picciuli_tui.screens.base import BookScreen
from picciuli_tui.screens.modals import (
    ChoiceField,
    ConfirmScreen,
    FormScreen,
    FormValues,
    PickScreen,
    TextField,
    trade_form,
)
from picciuli_tui.widgets import ListTable, amount_text

_PROVIDER_KINDS = {
    "etf": SecurityKind.ETF,
    "equity": SecurityKind.STOCK,
    "stock": SecurityKind.STOCK,
    "fund": SecurityKind.FUND,
    "mutual fund": SecurityKind.FUND,
    "mutualfund": SecurityKind.FUND,
    "bond": SecurityKind.BOND,
    "cryptocurrency": SecurityKind.CRYPTO,
    "crypto": SecurityKind.CRYPTO,
}


def guess_kind(info: SecurityInfo) -> SecurityKind:
    """Map the instrument type reported by a provider to a security kind."""
    return _PROVIDER_KINDS.get((info.kind or "").strip().lower(), SecurityKind.OTHER)


def looks_like_isin(text: str) -> bool:
    """Return whether a search text has the shape of an ISIN."""
    code = text.strip()
    return len(code) == 12 and code[:2].isalpha() and code.isalnum()


class InvestmentsScreen(BookScreen):
    """Holdings of every investment account and the list of securities."""

    SUB_TITLE = "Investments"
    MODE = "investments"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "new", "New security"),
        Binding("e", "edit", "Edit", show=False),
        Binding("d,delete", "delete", "Delete", show=False),
        Binding("f", "find", "Find"),
        Binding("b", "buy", "Buy"),
        Binding("x", "sell", "Sell"),
        Binding("p", "price", "Price"),
        Binding("r", "refresh", "Refresh"),
        Binding("h", "history", "History", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.valuations: list[AccountValuation] = []
        self.securities: list[Security] = []
        self.prices: dict[int, Price] = {}
        self.converted: dict[int, Decimal] = {}
        self._column_code: str | None = None

    def compose(self) -> ComposeResult:
        """Build the two tables."""
        yield from self.top_bar()
        yield Static(id="holdings-title", classes="pane-title")
        yield ListTable(id="holdings")
        yield Static(id="holdings-total", classes="pane-footer")
        yield Static(
            "[b]Securities[/] · n new · f find online · p enter a price",
            classes="pane-title",
        )
        yield ListTable(id="securities")
        yield Footer()

    def on_mount(self) -> None:
        """Add the columns."""
        self._add_columns(self.book.settings.get().currency_code)

    def _add_columns(self, code: str | None) -> None:
        """(Re)build the columns; the converted column is named after `code`."""
        converted = f"Price ({code or 'book'})"
        self._column_code = code
        holdings = self.query_one("#holdings", ListTable)
        holdings.clear(columns=True)
        for label, key in (
            ("Account", "account"),
            ("Security", "security"),
            ("Quantity", "quantity"),
            ("Price", "price"),
            (converted, "converted"),
            ("Cost", "cost"),
            ("Value", "value"),
            ("Gain", "gain"),
            ("%", "%"),
        ):
            holdings.add_column(label, key=key)
        securities = self.query_one("#securities", ListTable)
        securities.clear(columns=True)
        for label, key in (
            ("Name", "name"),
            ("Kind", "kind"),
            ("Symbol", "symbol"),
            ("ISIN", "isin"),
            ("Currency", "currency"),
            ("Price", "price"),
            (converted, "converted"),
            ("Date", "date"),
        ):
            securities.add_column(label, key=key)

    # Data

    def reload(self) -> None:
        """Read valuations, securities and prices."""
        code = self.book.settings.get().currency_code
        if code != self._column_code:
            self._add_columns(code)
        self.valuations = self.book.investments.valuations()
        self.securities = self.book.securities.list()
        self.prices = {}
        self.converted = {}
        for security in self.securities:
            price = self.book.securities.latest_price(security.id)
            if price is not None:
                self.prices[security.id] = price
                value = self.book.securities.latest_price_in_book_currency(security.id)
                if value is not None:
                    self.converted[security.id] = value
        self._show_title()
        self._show_holdings()
        self._show_securities()

    def _converted_cell(self, price: Decimal | None, converted: Decimal | None) -> Text:
        """Converted price, `?` when the rate is missing, blank without price."""
        if price is None:
            return Text("")
        if converted is None:
            return Text("?", justify="right", style="dim")
        code = self._column_code or ""
        return Text(price_text(rounded_price(converted), code).strip(), justify="right")

    def _show_title(self) -> None:
        app = self.picciuli
        try:
            provider = app.price_provider().name
        except PicciuliError:
            provider = self.book.settings.get().price_provider
        try:
            rates = app.rate_provider().name
        except PicciuliError:
            rates = self.book.settings.get().rate_provider
        live = f"live every {app.refresh_seconds:g} s" if app.live else "live off (l)"
        updated = (
            f" · updated {app.last_price_update:%H:%M:%S}"
            if app.last_price_update
            else ""
        )
        self.query_one("#holdings-title", Static).update(
            f"[b]Holdings[/] at market value · prices {provider} · "
            f"rates {rates} · {live}{updated}"
        )

    def _show_holdings(self) -> None:
        money = self.money
        table = self.query_one("#holdings", ListTable)
        selected = table.selected_key()
        table.clear()
        for valuation in self.valuations:
            account = valuation.account
            for holding in valuation.holdings:
                security = holding.security
                price = (
                    price_text(holding.price, security.currency)
                    if holding.price is not None
                    else Text("no price", style="dim")
                )
                gain = holding.unrealized_gain
                table.add_row(
                    account.name,
                    security.name,
                    Text(quantity_text(holding.quantity), justify="right"),
                    price,
                    self._converted_cell(holding.price, holding.converted_price),
                    amount_text(money, holding.cost_basis),
                    amount_text(money, holding.market_value)
                    if holding.market_value is not None
                    else Text("?", justify="right"),
                    amount_text(money, gain, plus=True) if gain is not None else "",
                    percent_text(gain, holding.cost_basis) if gain is not None else "",
                    key=f"{account.id}:{security.id}",
                )
            if valuation.cash or not valuation.holdings:
                table.add_row(
                    account.name,
                    Text("Cash", style="italic"),
                    "",
                    "",
                    "",
                    "",
                    amount_text(money, valuation.cash),
                    "",
                    "",
                    key=f"{account.id}:cash",
                )
        table.select_key(selected)
        cost = sum(v.cost_basis for v in self.valuations)
        value = sum(v.market_value for v in self.valuations)
        gain = sum(v.unrealized_gain for v in self.valuations)
        total = Text()
        for label, amount, plus in (
            ("Cost ", cost, False),
            ("   Market value ", value, False),
            ("   Unrealized gain ", gain, True),
        ):
            total.append(label, style="dim")
            total.append_text(amount_text(money, amount, plus=plus))
        total.append(f" {percent_text(gain, cost)}", style="dim")
        if not all(v.is_complete for v in self.valuations):
            total.append(
                "   some holdings have no price yet (counted at cost)", "yellow"
            )
        self.query_one("#holdings-total", Static).update(total)

    def _show_securities(self) -> None:
        table = self.query_one("#securities", ListTable)
        selected = table.selected_key()
        table.clear()
        for security in self.securities:
            price = self.prices.get(security.id)
            table.add_row(
                security.name,
                SECURITY_KIND_LABELS[security.kind],
                security.symbol or "",
                security.isin or "",
                security.currency,
                Text(price_text(price.price, security.currency), justify="right")
                if price
                else "",
                self._converted_cell(
                    price.price if price else None, self.converted.get(security.id)
                ),
                short_date(price.date) if price else "",
                key=str(security.id),
            )
        table.select_key(selected)

    # Selection

    def selected_account_id(self) -> int | None:
        """Return the account of the holding under the cursor."""
        key = self.query_one("#holdings", ListTable).selected_key()
        return int(key.split(":")[0]) if key else None

    def selected_security(self) -> Security | None:
        """Return the security under the cursor of the focused table."""
        holdings = self.query_one("#holdings", ListTable)
        if holdings.has_focus:
            key = holdings.selected_key() or ""
            ident = key.partition(":")[2]
        else:
            ident = self.query_one("#securities", ListTable).selected_key() or ""
        return next((s for s in self.securities if str(s.id) == ident), None)

    def on_data_table_row_selected(self, message: ListTable.RowSelected) -> None:
        """Open the account register from a holding, or edit a security."""
        message.stop()
        if message.data_table.id == "holdings":
            account_id = self.selected_account_id()
            if account_id is not None:
                self.app.push_screen(RegisterScreen(account_id))
        else:
            self.action_edit()

    # Securities

    def _security_form(
        self, security: Security | None, draft: SecurityDraft | None = None
    ) -> None:
        draft = draft or (SecurityDraft.of(security) if security else SecurityDraft())
        if not draft.currency:
            draft.currency = self.book.settings.get().currency_code or ""

        def submit(values: FormValues) -> Security:
            return save_security(
                self.book,
                SecurityDraft(
                    name=values["name"],
                    symbol=values["symbol"],
                    isin=values["isin"],
                    currency=values["currency"],
                    kind=values["kind"],
                    notes=values["notes"],
                ),
                security_id=security.id if security else None,
            )

        self.app.push_screen(
            FormScreen(
                "Edit security" if security else "New security",
                [
                    TextField("name", "Name", draft.name),
                    TextField(
                        "symbol",
                        "Symbol",
                        draft.symbol,
                        placeholder="provider symbol, e.g. VWCE.DE",
                    ),
                    TextField("isin", "ISIN", draft.isin),
                    TextField(
                        "currency", "Currency", draft.currency, placeholder="e.g. EUR"
                    ),
                    ChoiceField(
                        "kind",
                        "Kind",
                        [(label, kind) for kind, label in SECURITY_KIND_LABELS.items()],
                        draft.kind,
                    ),
                    TextField("notes", "Notes", draft.notes),
                ],
                submit,
                help=(
                    "The symbol is the one of the price provider: for Yahoo "
                    "Finance a suffix selects the exchange (VWCE.DE XETRA, "
                    "SWDA.MI Milan, VUSA.L London, AAPL Nasdaq). Securities "
                    "bought on gettex can use their XETRA listing."
                ),
            )
        )

    def action_new(self) -> None:
        """Create a security."""
        self._security_form(None)

    def action_edit(self) -> None:
        """Edit the selected security."""
        security = self.selected_security()
        if security is not None:
            self._security_form(security)

    def action_delete(self) -> None:
        """Delete the selected security after confirmation."""
        security = self.selected_security()
        if security is None:
            return

        def confirmed(answer: bool | None) -> None:
            if answer:
                self.attempt(lambda: self.book.securities.delete(security.id))
                self.reload()

        self.app.push_screen(
            ConfirmScreen(f"Delete {security.name!r} and its prices?"), confirmed
        )

    def action_find(self) -> None:
        """Search the price provider and create a security from a result."""

        def submit(values: FormValues) -> tuple[str, list[SecurityInfo]]:
            query = optional_text(values["query"])
            if query is None:
                raise InputError("type a name, symbol or ISIN")
            found = self.picciuli.price_provider().search(query)
            if not found:
                raise InputError(f"nothing found for {query!r}")
            return query, found

        self.app.push_screen(
            FormScreen(
                "Find a security",
                [TextField("query", "Search", placeholder="name, symbol or ISIN")],
                submit,
                save_label="Search",
                help="The search uses the price provider selected in the settings.",
            ),
            self._found,
        )

    def _found(self, result: tuple[str, list[SecurityInfo]] | None) -> None:
        if result is None:
            return
        query, found = result
        items = [
            (
                f"{info.symbol:<16} {info.name} · {info.exchange or '?'}"
                f" · {info.kind or '?'}",
                info,
            )
            for info in found
        ]

        def picked(info: SecurityInfo | None) -> None:
            if info is None:
                return
            currency = info.currency or ""
            if not currency:
                try:
                    currency = (
                        self.picciuli.price_provider().latest(info.symbol).currency
                        or ""
                    )
                except PicciuliError:
                    currency = ""
            self._security_form(
                None,
                SecurityDraft(
                    name=info.name,
                    symbol=info.symbol,
                    isin=query.strip().upper() if looks_like_isin(query) else "",
                    currency=currency,
                    kind=guess_kind(info),
                ),
            )

        self.app.push_screen(PickScreen("Pick a listing", items), picked)

    def action_price(self) -> None:
        """Enter the price of the selected security by hand."""
        security = self.selected_security()
        if security is None:
            self.notify("Select a security first.")
            return
        latest = self.prices.get(security.id)
        today = self.today()

        def submit(values: FormValues) -> Price:
            return save_price(
                self.book,
                security.id,
                date=values["date"],
                price=values["price"],
                today=today,
            )

        self.app.push_screen(
            FormScreen(
                f"Price of {security.name}",
                [
                    TextField("date", "Date", today.isoformat()),
                    TextField(
                        "price",
                        f"Price ({security.currency})",
                        f"{latest.price:f}" if latest else "",
                    ),
                ],
                submit,
                help="One price per day: a new price replaces the one of that day.",
            )
        )

    def action_refresh(self) -> None:
        """Download the latest prices."""
        self.picciuli.refresh_prices()

    def action_history(self) -> None:
        """Download daily prices since the first investment transaction."""
        days = [
            transactions[0].date
            for valuation in self.valuations
            if (
                transactions := self.book.transactions.list(
                    account_id=valuation.account.id, limit=1
                )
            )
        ]
        if not days:
            self.notify("Nothing has been bought yet.")
            return
        self.picciuli.refresh_prices(history_start=min(days))

    # Trades

    def _trade_form(self, selling: bool) -> None:
        security = self.selected_security()
        form = trade_form(
            self.book,
            self.money,
            today=self.today(),
            selling=selling,
            account_id=self.selected_account_id(),
            security_id=security.id if security else None,
        )
        if form is None:
            self.notify("Create an investment account and a security first.")
            return
        self.app.push_screen(
            form,
            self._traded,
        )

    def _traded(self, transaction: Transaction | None) -> None:
        if transaction is None:
            return
        gain = next(
            (
                s.amount
                for s in transaction.external_splits
                if s.memo == "Realized gain"
            ),
            None,
        )
        if gain is not None:
            self.notify(
                f"Realized gain: {self.money.amount(gain, plus=True)}", title="Sold"
            )

    def action_buy(self) -> None:
        """Record a purchase of shares."""
        self._trade_form(selling=False)

    def action_sell(self) -> None:
        """Record a sale of shares."""
        self._trade_form(selling=True)
