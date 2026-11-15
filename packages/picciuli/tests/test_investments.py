from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from picciuli import (
    Account,
    AccountSplit,
    AccountType,
    Book,
    Category,
    ConflictError,
    ExternalSplit,
    NotFoundError,
    Security,
    SecurityKind,
    Settings,
    TransactionKind,
    ValidationError,
)
from picciuli.errors import PriceProviderError
from picciuli.prices import PricePoint, PriceProvider, Quote
from picciuli.rates import ExchangeRateProvider, RatePoint, RateQuote

from .conftest import d


@pytest.fixture
def broker(book: Book) -> Account:
    return book.accounts.create("Broker", AccountType.INVESTMENT)


@pytest.fixture
def etf(book: Book) -> Security:
    return book.securities.create(
        "All-World", currency="USD", kind="etf", symbol="VWCE.DE", isin="IE00BK5BQT80"
    )


@pytest.fixture
def gains(book: Book) -> Category:
    return book.categories.create("Capital gains")


def buy(
    book: Book, broker: Account, etf: Security, day: int, qty: str, cost: int
) -> None:
    book.investments.record_buy(
        d(day),
        account_id=broker.id,
        security_id=etf.id,
        quantity=Decimal(qty),
        cost=cost,
    )


class TestSecurities:
    def test_create_update_list_delete(self, book: Book) -> None:
        apple = book.securities.create(
            " Apple ", currency="usd", symbol=" AAPL ", isin="us0378331005"
        )
        assert apple == Security(
            apple.id, "Apple", "AAPL", "US0378331005", "USD", SecurityKind.STOCK, None
        )
        bond = book.securities.create("Bond", currency="EUR", kind=SecurityKind.BOND)
        assert [s.name for s in book.securities.list()] == ["Apple", "Bond"]
        changed = book.securities.update(
            bond.id, name="BTP", currency="eur", kind="other", symbol="", notes=" x "
        )
        assert (changed.name, changed.kind, changed.symbol, changed.notes) == (
            "BTP",
            SecurityKind.OTHER,
            None,
            "x",
        )
        book.securities.set_price(bond.id, d(1), 100)
        book.securities.delete(bond.id)
        with pytest.raises(NotFoundError):
            book.securities.get(bond.id)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"currency": "EURO"},
            {"currency": "EUR", "isin": "US0378331006"},
            {"currency": "EUR", "isin": "US037833100"},
            {"currency": "EUR", "kind": "warrant"},
        ],
    )
    def test_invalid(self, book: Book, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            book.securities.create("X", **kwargs)  # type: ignore[arg-type]

    def test_unique_name_and_isin(self, book: Book, etf: Security) -> None:
        with pytest.raises(ConflictError, match="named"):
            book.securities.create("all-world", currency="EUR")
        with pytest.raises(ConflictError, match="ISIN"):
            book.securities.create("Other", currency="EUR", isin="IE00BK5BQT80")
        other = book.securities.create("Other", currency="EUR")
        with pytest.raises(ConflictError):
            book.securities.update(other.id, isin="ie00bk5bqt80")

    def test_used_security_cannot_be_deleted(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        buy(book, broker, etf, 1, "1", 100)
        with pytest.raises(ConflictError, match="used"):
            book.securities.delete(etf.id)

    def test_prices(self, book: Book, etf: Security) -> None:
        book.securities.set_price(etf.id, d(2), Decimal("10.5"))
        book.securities.set_price(etf.id, d(5), Decimal("11"), source="manual")
        replaced = book.securities.set_price(etf.id, d(2), Decimal("10.25"))
        assert replaced.price == Decimal("10.25")
        assert [p.date for p in book.securities.prices(etf.id)] == [d(2), d(5)]
        assert book.securities.prices(etf.id, start=d(3), end=d(9))[0].source == (
            "manual"
        )
        assert book.securities.latest_price(etf.id, as_of=d(1)) is None
        latest = book.securities.latest_price(etf.id, as_of=d(4))
        assert latest is not None and latest.price == Decimal("10.25")
        latest = book.securities.latest_price(etf.id)
        assert latest is not None and latest.date == d(5)
        book.securities.delete_price(etf.id, d(5))
        with pytest.raises(NotFoundError):
            book.securities.delete_price(etf.id, d(5))
        for bad in (0, Decimal("1.123456789"), 1.5, Decimal("NaN"), True):
            with pytest.raises(ValidationError):
                book.securities.set_price(etf.id, d(1), bad)  # type: ignore[arg-type]

    def test_exchange_rates(self, book: Book) -> None:
        book.securities.set_exchange_rate("eur", d(1), Decimal("1.1"))
        book.securities.set_exchange_rate("EUR", d(3), Decimal("1.2"))
        assert [r.rate for r in book.securities.exchange_rates("EUR")] == [
            Decimal("1.1"),
            Decimal("1.2"),
        ]
        assert len(book.securities.exchange_rates("EUR", start=d(2), end=d(4))) == 1
        rate = book.securities.latest_exchange_rate("EUR", as_of=d(2))
        assert rate is not None and rate.rate == Decimal("1.1")
        assert book.securities.latest_exchange_rate("GBP") is None


class TestTransactionsWithShares:
    def test_split_requires_investment_account_and_both_fields(
        self, book: Book, checking: Account, broker: Account, etf: Security
    ) -> None:
        create = book.transactions.create
        with pytest.raises(ValidationError, match="not an investment"):
            create(d(1), [AccountSplit(checking.id, 0, security_id=etf.id, quantity=1)])  # type: ignore[arg-type]
        with pytest.raises(ValidationError, match="both"):
            create(d(1), [AccountSplit(broker.id, 0, security_id=etf.id)])
        with pytest.raises(ValidationError, match="cannot be zero"):
            create(d(1), [AccountSplit(broker.id, 0, security_id=etf.id, quantity=0)])  # type: ignore[arg-type]
        with pytest.raises(NotFoundError):
            create(d(1), [AccountSplit(broker.id, 0, security_id=99, quantity=1)])  # type: ignore[arg-type]

    def test_zero_amount_stock_split(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        buy(book, broker, etf, 1, "1", 1000)
        split = book.transactions.create(
            d(2),
            [AccountSplit(broker.id, 0, security_id=etf.id, quantity=Decimal(9))],
            description="Stock split 10:1",
        )
        assert split.kind is TransactionKind.TRANSFER
        (holding,) = book.investments.holdings(broker.id)
        assert (holding.quantity, holding.cost_basis) == (Decimal(10), 1000)

    def test_quantities_cannot_go_negative(
        self, book: Book, checking: Account, broker: Account, etf: Security
    ) -> None:
        buy(book, broker, etf, 5, "2", 1000)
        sale = book.investments.record_sell(
            d(6), account_id=broker.id, security_id=etf.id, quantity=1, proceeds=600
        )
        purchase = book.transactions.list(account_id=broker.id)[0]
        with pytest.raises(ValidationError, match="negative"):
            book.transactions.delete(purchase.id)
        with pytest.raises(ValidationError, match="negative"):
            book.transactions.update(purchase.id, date=d(7))
        with pytest.raises(ValidationError, match="negative"):
            book.transactions.create(
                d(4),
                [
                    AccountSplit(broker.id, -1, security_id=etf.id, quantity=-1),  # type: ignore[arg-type]
                    AccountSplit(checking.id, 1),
                ],
            )
        # Same-day purchase and sale are fine whatever their order.
        book.transactions.update(sale.id, date=d(5))
        book.transactions.update(sale.id, description="Sold")
        assert book.transactions.get(sale.id).account_splits[0].quantity == -1
        book.transactions.delete(sale.id)
        book.transactions.delete(purchase.id)

    def test_account_rules(
        self, book: Book, checking: Account, broker: Account, etf: Security
    ) -> None:
        book.investments.record_buy(
            d(1),
            account_id=broker.id,
            security_id=etf.id,
            quantity=1,
            cost=500,
            from_account_id=checking.id,
        )
        with pytest.raises(ConflictError, match="investment account"):
            book.accounts.update(broker.id, type=AccountType.SAVINGS)
        book.accounts.update(broker.id, name="Scalable")
        # The balance is zero only once the share is moved out at its cost.
        book.transactions.create(
            d(2),
            [
                AccountSplit(broker.id, -500, security_id=etf.id, quantity=Decimal(-1)),
                AccountSplit(checking.id, 500),
            ],
        )
        book.transactions.create(
            d(3),
            [
                AccountSplit(broker.id, 0, security_id=etf.id, quantity=Decimal(1)),
            ],
        )
        with pytest.raises(ConflictError, match="share"):
            book.accounts.close(broker.id, on=d(4))


class TestBuyAndSell:
    def test_buy_from_another_account_with_fee(
        self, book: Book, checking: Account, broker: Account, etf: Security
    ) -> None:
        fees = book.categories.create("Fees")
        tx = book.investments.record_buy(
            d(1),
            account_id=broker.id,
            security_id=etf.id,
            quantity=1,
            cost=3500,
            from_account_id=checking.id,
            fee=99,
            fee_category_id=fees.id,
        )
        assert tx.description == "Buy All-World"
        assert tx.splits == (
            AccountSplit(broker.id, 3500, security_id=etf.id, quantity=Decimal(1)),
            AccountSplit(checking.id, -3599),
            ExternalSplit(-99, fees.id, "Fee"),
        )
        assert tx.kind is TransactionKind.EXPENSE
        assert book.accounts.balance(broker.id) == 3500

    def test_buy_with_cash_of_the_investment_account(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        book.transactions.record_income(d(1), 10000, account_id=broker.id)
        buy(book, broker, etf, 2, "1", 3500)
        valuation = book.investments.valuation(broker.id)
        assert (valuation.balance, valuation.cash, valuation.cost_basis) == (
            10000,
            6500,
            3500,
        )

    @pytest.mark.parametrize("kwargs", [{"cost": 0}, {"quantity": 0}, {"fee": -1}])
    def test_buy_invalid(
        self, book: Book, broker: Account, etf: Security, kwargs: dict[str, int]
    ) -> None:
        args: dict[str, int] = {"quantity": 1, "cost": 100, **kwargs}
        with pytest.raises(ValidationError):
            book.investments.record_buy(
                d(1),
                account_id=broker.id,
                security_id=etf.id,
                **args,  # type: ignore[arg-type]
            )

    def test_sell_with_gain_fee_and_tax(
        self,
        book: Book,
        checking: Account,
        broker: Account,
        etf: Security,
        gains: Category,
    ) -> None:
        buy(book, broker, etf, 1, "1", 3500)
        tx = book.investments.record_sell(
            d(2),
            account_id=broker.id,
            security_id=etf.id,
            quantity=1,
            proceeds=4000,
            to_account_id=checking.id,
            fee=100,
            tax=130,
            gain_category_id=gains.id,
        )
        assert tx.description == "Sell All-World"
        assert tx.splits == (
            AccountSplit(broker.id, -3500, security_id=etf.id, quantity=Decimal(-1)),
            AccountSplit(checking.id, 3770),
            ExternalSplit(500, gains.id, "Realized gain"),
            ExternalSplit(-100, None, "Fee"),
            ExternalSplit(-130, None, "Tax"),
        )
        assert tx.kind is TransactionKind.MIXED
        assert book.investments.holdings(broker.id) == []

    def test_sell_at_a_loss_keeps_cash_in_the_account(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        buy(book, broker, etf, 1, "2", 1000)
        tx = book.investments.record_sell(
            d(2), account_id=broker.id, security_id=etf.id, quantity=1, proceeds=400
        )
        assert tx.kind is TransactionKind.EXPENSE
        assert tx.net_amount == -100
        valuation = book.investments.valuation(broker.id)
        assert (valuation.cash, valuation.cost_basis) == (-600, 500)

    def test_sell_without_gain_or_received_money(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        buy(book, broker, etf, 1, "1", 1000)
        tx = book.investments.record_sell(
            d(2),
            account_id=broker.id,
            security_id=etf.id,
            quantity=1,
            proceeds=1000,
            fee=1000,
        )
        assert tx.splits == (
            AccountSplit(broker.id, -1000, security_id=etf.id, quantity=Decimal(-1)),
            ExternalSplit(-1000, None, "Fee"),
        )

    def test_cannot_sell_more_than_held_on_that_day(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        buy(book, broker, etf, 5, "1", 1000)
        for day, qty in ((4, "1"), (6, "1.5")):
            with pytest.raises(ValidationError, match="only"):
                book.investments.record_sell(
                    d(day),
                    account_id=broker.id,
                    security_id=etf.id,
                    quantity=Decimal(qty),
                    proceeds=100,
                )

    def test_average_and_fifo_costs(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        buy(book, broker, etf, 1, "1", 1000)
        buy(book, broker, etf, 2, "2", 4000)

        def cost(qty: str) -> int:
            return book.investments.sale_cost(
                broker.id, etf.id, Decimal(qty), date=d(9)
            )

        assert cost("1") == 1667
        assert cost("3") == 5000
        book.settings.update(cost_method="fifo")
        assert cost("1") == 1000
        assert cost("1.5") == 2000
        book.investments.record_sell(
            d(3), account_id=broker.id, security_id=etf.id, quantity=1, proceeds=3000
        )
        # FIFO consumed the first lot; half of the second lot costs 1000.
        assert cost("1") == 2000
        assert cost("0.5") == 1000
        book.settings.update(cost_method="average")
        assert cost("1") == 2000

    def test_fifo_lot_split_partially_and_repeatedly(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        book.settings.update(cost_method="fifo")
        buy(book, broker, etf, 1, "3", 999)
        buy(book, broker, etf, 2, "1", 500)
        for day in (3, 4):
            book.investments.record_sell(
                d(day),
                account_id=broker.id,
                security_id=etf.id,
                quantity=1,
                proceeds=400,
            )
        assert book.investments.sale_cost(broker.id, etf.id, 2, date=d(9)) == 833


class TestValuation:
    def test_market_value_with_exchange_rates(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        book.settings.update(currency_code="EUR")
        buy(book, broker, etf, 1, "1.5", 5000)
        valuation = book.investments.valuation(broker.id)
        (holding,) = valuation.holdings
        assert holding.market_value is None and holding.unrealized_gain is None
        assert not valuation.is_complete
        # The purchase used the account's own cash (-5000), shares count at cost.
        assert valuation.market_value == 0
        book.securities.set_price(etf.id, d(2), Decimal("40"))
        assert book.investments.valuation(broker.id).holdings[0].exchange_rate is None
        book.securities.set_exchange_rate("USD", d(2), Decimal("0.9"))
        book.securities.set_price(etf.id, d(3), Decimal("41"))
        early = book.investments.valuation(broker.id, as_of=d(2))
        assert early.holdings[0].market_value == 5400
        valuation = book.investments.valuation(broker.id)
        (holding,) = valuation.holdings
        assert (holding.price, holding.price_date, holding.market_value) == (
            Decimal("41"),
            d(3),
            5535,
        )
        assert holding.unrealized_gain == 535
        assert valuation.is_complete
        assert valuation.unrealized_gain == 535
        assert book.investments.valuation(broker.id, as_of=d(1)).as_of == d(1)

    def test_book_currency_needs_no_rate(self, book: Book, broker: Account) -> None:
        local = book.securities.create("Local", currency="USD")
        buy(book, broker, local, 1, "3", 3000)
        book.securities.set_price(local.id, d(1), Decimal("12.345"))
        assert book.investments.holdings(broker.id)[0].market_value == 3704

    def test_valuations_and_net_worth(
        self, book: Book, checking: Account, broker: Account, etf: Security
    ) -> None:
        loan = book.accounts.create("Loan", AccountType.LOAN, opening_balance=-500)
        closed = book.accounts.create("Old broker", AccountType.INVESTMENT)
        book.accounts.close(closed.id, on=d(1))
        book.transactions.record_income(d(1), 10000, account_id=checking.id)
        book.investments.record_buy(
            d(2),
            account_id=broker.id,
            security_id=etf.id,
            quantity=2,
            cost=3000,
            from_account_id=checking.id,
        )
        book.securities.set_price(etf.id, d(3), Decimal("20"))
        assert [v.account.id for v in book.investments.valuations()] == [broker.id]
        assert len(book.investments.valuations(include_closed=True)) == 2
        assert len(book.investments.valuations(as_of=d(1), include_closed=False)) == 1
        worth = book.investments.net_worth()
        assert (worth.assets, worth.liabilities, worth.net_worth) == (
            11000,
            -500,
            10500,
        )
        assert book.accounts.net_worth().assets == 10000
        assert book.investments.net_worth(as_of=d(2)).assets == 10000
        assert loan.account_class.value == "liability"


class FakeProvider(PriceProvider):
    id = "fake"
    name = "Fake"

    def __init__(self) -> None:
        self.quotes: dict[str, Quote] = {}
        self.failing: set[str] = set()
        self.history_calls: list[tuple[str, dt.date, dt.date]] = []

    def add(self, symbol: str, price: str, currency: str | None, day: dt.date) -> None:
        moment = dt.datetime.combine(day, dt.time(17), dt.timezone.utc)
        self.quotes[symbol] = Quote(symbol, Decimal(price), currency, moment)

    def latest(self, symbol: str) -> Quote:
        if symbol in self.failing or symbol not in self.quotes:
            raise PriceProviderError(f"no quote for {symbol}")
        return self.quotes[symbol]

    def history(self, symbol: str, start: dt.date, end: dt.date) -> list[PricePoint]:
        self.history_calls.append((symbol, start, end))
        return [PricePoint(start, self.quotes[symbol].price / 2)]


class FakeRates(ExchangeRateProvider):
    id = "fakerates"
    name = "Fake rates"

    def __init__(self) -> None:
        self.rates: dict[tuple[str, str], Decimal] = {}

    def latest(self, currency: str, base: str) -> RateQuote:
        rate = self.rates.get((currency, base))
        if rate is None:
            raise PriceProviderError(f"no rate for {currency}{base}")
        moment = dt.datetime.combine(d(10), dt.time(17), dt.timezone.utc)
        return RateQuote(currency, base, rate, moment)

    def history(
        self, currency: str, base: str, start: dt.date, end: dt.date
    ) -> list[RatePoint]:
        return [RatePoint(start, self.rates[(currency, base)] / 2)]


class TestRefreshPrices:
    def test_refresh_stores_prices_and_rates(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        book.settings.update(currency_code="EUR")
        euro = book.securities.create("Euro ETF", currency="EUR", symbol="EUR1")
        book.securities.create("Manual", currency="EUR")
        swiss = book.securities.create("Swiss", currency="CHF", symbol="CH1")
        bad = book.securities.create("Broken", currency="EUR", symbol="BAD")
        mismatch = book.securities.create("Mismatch", currency="EUR", symbol="MIS")
        provider = FakeProvider()
        provider.add("VWCE.DE", "100", "USD", d(10))
        provider.add("EUR1", "50.5", None, d(10))
        provider.add("CH1", "10", "CHF", d(10))
        provider.add("MIS", "10", "USD", d(10))
        provider.failing.add("BAD")
        rates = FakeRates()
        rates.rates[("USD", "EUR")] = Decimal("0.9")
        update = book.investments.refresh_prices(
            provider, rate_provider=rates, history_start=d(1)
        )
        assert {(p.security_id, p.date, p.price) for p in update.prices} == {
            (etf.id, d(1), Decimal(50)),
            (etf.id, d(10), Decimal(100)),
            (euro.id, d(1), Decimal("25.25")),
            (euro.id, d(10), Decimal("50.5")),
            (swiss.id, d(1), Decimal(5)),
            (swiss.id, d(10), Decimal(10)),
        }
        assert all(p.source == "fake" for p in update.prices)
        assert [(r.currency, r.date, r.rate) for r in update.exchange_rates] == [
            ("USD", d(1), Decimal("0.45")),
            ("USD", d(10), Decimal("0.9")),
        ]
        assert update.errors == (
            "Broken: no quote for BAD",
            "Mismatch: MIS is quoted in USD, not EUR",
            "CHF: no rate for CHFEUR",
        )
        assert bad.id and mismatch.id
        buy(book, broker, etf, 2, "1", 8000)
        assert book.investments.holdings(broker.id)[0].market_value == 9000

    def test_refresh_selected_securities_and_errors(
        self, book: Book, etf: Security
    ) -> None:
        manual = book.securities.create("Manual", currency="EUR")
        provider = FakeProvider()
        provider.add("VWCE.DE", "100", "USD", d(10))
        rates = FakeRates()
        rates.rates[("USD", "USD")] = Decimal(1)
        update = book.investments.refresh_prices(
            provider,
            rate_provider=rates,
            security_ids=[etf.id, manual.id],
            history_start=dt.date.today() + dt.timedelta(days=1),
        )
        assert len(update.prices) == 1
        assert update.errors == ("Manual: no symbol to look up",)
        assert provider.history_calls == []
        # Same day: the new quote replaces the old one.
        provider.add("VWCE.DE", "101", "USD", d(10))
        book.investments.refresh_prices(provider, rate_provider=rates)
        assert [p.price for p in book.securities.prices(etf.id)] == [Decimal(101)]
        with pytest.raises(NotFoundError):
            book.investments.refresh_prices(provider, security_ids=[999])

    def test_rates_need_a_currency_code_and_may_fail(
        self, book: Book, etf: Security
    ) -> None:
        provider = FakeProvider()
        provider.add("VWCE.DE", "100", "USD", d(10))
        book.securities.create("Euro", currency="EUR", symbol="E")
        provider.add("E", "1", "EUR", d(10))
        update = book.investments.refresh_prices(provider, rate_provider=FakeRates())
        assert update.errors == ("EUR: no rate for EURUSD",)
        book.settings.update(currency_code=None)
        update = book.investments.refresh_prices(provider, rate_provider=FakeRates())
        assert update.errors == (
            "EUR: set the book currency code to convert prices",
            "USD: set the book currency code to convert prices",
        )

    def test_default_providers_come_from_settings(
        self, book: Book, etf: Security, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created: list[str] = []
        prices = FakeProvider()
        prices.add("VWCE.DE", "100", "USD", d(10))

        def fake_create(provider_id: str) -> PriceProvider:
            created.append(provider_id)
            return prices

        def fake_rates(provider_id: str) -> ExchangeRateProvider:
            created.append(f"rates:{provider_id}")
            rates = FakeRates()
            rates.rates[("USD", "EUR")] = Decimal("0.9")
            return rates

        monkeypatch.setattr(
            "picciuli.services.investments.create_provider", fake_create
        )
        monkeypatch.setattr(
            "picciuli.services.investments.create_rate_provider", fake_rates
        )
        book.settings.update(currency_code="EUR")
        update = book.investments.refresh_prices()
        assert update.errors == ()
        assert created == ["yahoo", "rates:yahoo"]

    def test_unknown_rate_provider_is_reported(
        self, book: Book, etf: Security, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book.settings.update(currency_code="EUR")
        monkeypatch.setattr(
            "picciuli.services.investments.read_settings",
            lambda session: Settings("€", 2, "EUR", rate_provider="gone"),
        )
        provider = FakeProvider()
        provider.add("VWCE.DE", "100", "USD", d(10))
        update = book.investments.refresh_prices(provider)
        assert len(update.prices) == 1
        assert update.errors == (
            "exchange rates: unknown exchange-rate provider 'gone'",
        )

    def test_refresh_exchange_rates(self, book: Book, etf: Security) -> None:
        book.settings.update(currency_code="EUR")
        book.securities.create("Euro", currency="EUR")
        rates = FakeRates()
        rates.rates[("USD", "EUR")] = Decimal("0.9")
        update = book.investments.refresh_exchange_rates(rates, history_start=d(1))
        assert update.prices == ()
        assert [(r.currency, r.rate) for r in update.exchange_rates] == [
            ("USD", Decimal("0.45")),
            ("USD", Decimal("0.9")),
        ]
        update = book.investments.refresh_exchange_rates(
            rates, currencies=["gbp", "eur"]
        )
        assert update.errors == ("GBP: no rate for GBPEUR",)
        assert (
            book.investments.refresh_exchange_rates(rates, currencies=[]).errors == ()
        )


class TestConvertedPrices:
    def test_holding_and_security_prices_in_book_currency(
        self, book: Book, broker: Account, etf: Security
    ) -> None:
        book.settings.update(currency_code="EUR")
        euro = book.securities.create("Euro", currency="EUR")
        buy(book, broker, etf, 1, "1", 100)
        assert book.securities.latest_price_in_book_currency(etf.id) is None
        book.securities.set_price(etf.id, d(2), Decimal(100))
        book.securities.set_price(euro.id, d(2), Decimal(50))
        assert book.securities.latest_price_in_book_currency(etf.id) is None
        assert book.investments.holdings(broker.id)[0].converted_price is None
        assert book.securities.latest_price_in_book_currency(euro.id) == 50
        book.securities.set_exchange_rate("USD", d(3), Decimal("0.9"))
        assert book.securities.latest_price_in_book_currency(etf.id) == 90
        assert book.securities.latest_price_in_book_currency(etf.id, as_of=d(2)) is None
        assert book.securities.latest_price_in_book_currency(etf.id, as_of=d(1)) is None
        assert book.investments.holdings(broker.id)[0].converted_price == 90
