from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_tests.helpers import API, FakeClock, FakePrices, FakeRates, create_account, d


def create_security(api: TestClient, **body: Any) -> dict[str, Any]:
    body = {"name": "World ETF", "currency": "EUR", "kind": "etf", **body}
    response = api.post(f"{API}/securities", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


class TestSecurities:
    def test_crud(self, alice: TestClient) -> None:
        security = create_security(alice, symbol="VWCE.DE", isin="IE00BK5BQT80")
        assert security == {
            "id": security["id"],
            "name": "World ETF",
            "symbol": "VWCE.DE",
            "isin": "IE00BK5BQT80",
            "currency": "EUR",
            "kind": "etf",
            "notes": None,
        }
        url = f"{API}/securities/{security['id']}"
        assert alice.get(url).json() == security
        assert alice.get(f"{API}/securities").json() == [security]
        updated = alice.patch(url, json={"symbol": None, "notes": "manual"}).json()
        assert (updated["symbol"], updated["notes"]) == (None, "manual")
        assert alice.delete(url).status_code == 204
        assert alice.get(url).status_code == 404

    def test_invalid_currency(self, alice: TestClient) -> None:
        response = alice.post(
            f"{API}/securities", json={"name": "Bad", "currency": "EURO"}
        )
        assert response.status_code == 422

    def test_prices(self, alice: TestClient) -> None:
        security = create_security(alice)
        url = f"{API}/securities/{security['id']}"
        stored = alice.put(f"{url}/prices/2025-01-10", json={"price": "101.25"})
        assert stored.json() == {
            "security_id": security["id"],
            "date": "2025-01-10",
            "price": "101.25",
            "source": None,
        }
        alice.put(f"{url}/prices/2025-01-11", json={"price": 102, "source": "me"})
        prices = alice.get(f"{url}/prices", params={"start": "2025-01-11"}).json()
        assert [(p["date"], p["price"]) for p in prices] == [("2025-01-11", "102")]

        latest = alice.get(f"{url}/latest-price", params={"as_of": "2025-01-10"})
        assert latest.json()["price"]["price"] == "101.25"
        assert latest.json()["price_in_book_currency"] is None

        assert alice.delete(f"{url}/prices/2025-01-11").status_code == 204
        assert len(alice.get(f"{url}/prices").json()) == 1

    def test_price_must_be_positive(self, alice: TestClient) -> None:
        security = create_security(alice)
        response = alice.put(
            f"{API}/securities/{security['id']}/prices/2025-01-10", json={"price": "0"}
        )
        assert response.status_code == 422

    def test_latest_price_unknown(self, alice: TestClient) -> None:
        security = create_security(alice)
        latest = alice.get(f"{API}/securities/{security['id']}/latest-price").json()
        assert latest == {"price": None, "price_in_book_currency": None}


class TestExchangeRates:
    def test_rates(self, alice: TestClient) -> None:
        alice.patch(f"{API}/settings", json={"currency_code": "EUR"})
        assert alice.get(f"{API}/exchange-rates/USD/latest").json() == {
            "exchange_rate": None
        }
        stored = alice.put(f"{API}/exchange-rates/USD/2025-01-10", json={"rate": "0.9"})
        assert stored.json() == {"currency": "USD", "date": "2025-01-10", "rate": "0.9"}
        rates = alice.get(f"{API}/exchange-rates/USD").json()
        assert [r["rate"] for r in rates] == ["0.9"]
        latest = alice.get(f"{API}/exchange-rates/USD/latest").json()
        assert latest["exchange_rate"]["rate"] == "0.9"

        security = create_security(alice, name="Apple", currency="USD")
        alice.put(
            f"{API}/securities/{security['id']}/prices/2025-01-10",
            json={"price": "200"},
        )
        latest = alice.get(f"{API}/securities/{security['id']}/latest-price").json()
        assert latest["price_in_book_currency"] == "180"

    def test_decimals_never_use_exponent_notation(self, alice: TestClient) -> None:
        security = create_security(alice)
        url = f"{API}/securities/{security['id']}/prices/2025-01-10"
        assert alice.put(url, json={"price": "1E+3"}).json()["price"] == "1000"


@pytest.fixture
def portfolio(alice: TestClient) -> dict[str, int]:
    alice.patch(f"{API}/settings", json={"currency_code": "EUR"})
    checking = create_account(alice, "Checking", opening_balance=100000)
    broker = create_account(alice, "Broker", "investment")
    etf = create_security(alice, symbol="VWCE.DE")
    gains = alice.post(f"{API}/categories", json={"name": "Capital gains"}).json()
    response = alice.post(
        f"{API}/investments/buy",
        json={
            "date": "2025-01-10",
            "account_id": broker["id"],
            "security_id": etf["id"],
            "quantity": "2",
            "cost": 20000,
            "from_account_id": checking["id"],
        },
    )
    assert response.status_code == 201, response.text
    return {
        "checking": checking["id"],
        "broker": broker["id"],
        "etf": etf["id"],
        "gains": gains["id"],
    }


class TestInvestments:
    def test_buy(self, alice: TestClient, portfolio: dict[str, int]) -> None:
        [buy] = alice.get(
            f"{API}/transactions", params={"account_id": portfolio["broker"]}
        ).json()
        assert buy["kind"] == "transfer"
        share = next(s for s in buy["splits"] if s["security_id"] is not None)
        assert (share["quantity"], share["amount"]) == ("2", 20000)

    def test_holdings_and_valuation(
        self, alice: TestClient, portfolio: dict[str, int]
    ) -> None:
        url = f"{API}/investments/{portfolio['broker']}"
        [holding] = alice.get(f"{url}/holdings").json()
        assert holding["quantity"] == "2"
        assert holding["market_value"] is None

        alice.put(
            f"{API}/securities/{portfolio['etf']}/prices/2025-01-15",
            json={"price": "120"},
        )
        valuation = alice.get(f"{url}/valuation").json()
        assert valuation["balance"] == 20000
        assert valuation["market_value"] == 24000
        assert valuation["unrealized_gain"] == 4000
        assert valuation["is_complete"] is True
        assert valuation["holdings"][0]["converted_price"] == "120"

        before = alice.get(f"{url}/valuation", params={"as_of": "2025-01-12"}).json()
        assert before["market_value"] == 20000
        assert before["is_complete"] is False

        valuations = alice.get(f"{API}/investments/valuations").json()
        assert [v["account"]["name"] for v in valuations] == ["Broker"]
        net = alice.get(f"{API}/investments/net-worth").json()
        assert net["net_worth"] == 104000

    def test_sale_cost_and_sell(
        self, alice: TestClient, portfolio: dict[str, int]
    ) -> None:
        cost = alice.get(
            f"{API}/investments/{portfolio['broker']}/sale-cost",
            params={
                "security_id": portfolio["etf"],
                "quantity": "0.5",
                "date": "2025-02-01",
            },
        )
        assert cost.json() == {"cost": 5000}
        sale = alice.post(
            f"{API}/investments/sell",
            json={
                "date": "2025-02-01",
                "account_id": portfolio["broker"],
                "security_id": portfolio["etf"],
                "quantity": "0.5",
                "proceeds": 7000,
                "to_account_id": portfolio["checking"],
                "gain_category_id": portfolio["gains"],
            },
        )
        assert sale.status_code == 201, sale.text
        assert sale.json()["net_amount"] == 2000
        [holding] = alice.get(
            f"{API}/investments/{portfolio['broker']}/holdings"
        ).json()
        assert holding["quantity"] == "1.5"

    def test_cannot_sell_more_than_held(
        self, alice: TestClient, portfolio: dict[str, int]
    ) -> None:
        response = alice.post(
            f"{API}/investments/sell",
            json={
                "date": "2025-02-01",
                "account_id": portfolio["broker"],
                "security_id": portfolio["etf"],
                "quantity": "3",
                "proceeds": 1,
            },
        )
        assert response.status_code in (409, 422)


class TestRefresh:
    def test_prices_are_shared_and_cached_between_users(
        self,
        alice: TestClient,
        bob: TestClient,
        fake_prices: FakePrices,
        clock: FakeClock,
    ) -> None:
        fake_prices.add("VWCE.DE", "130.5", "EUR", d(10))
        for user in (alice, bob):
            user.patch(f"{API}/settings", json={"currency_code": "EUR"})
            create_security(user, symbol="VWCE.DE")
            update = user.post(f"{API}/investments/refresh-prices").json()
            assert update["errors"] == []
            assert [p["price"] for p in update["prices"]] == ["130.5"]
        assert fake_prices.calls == ["VWCE.DE"]

        clock.now += 15 * 60
        alice.post(f"{API}/investments/refresh-prices", json={})
        assert fake_prices.calls == ["VWCE.DE", "VWCE.DE"]

    def test_refresh_reports_errors_and_converts(
        self, alice: TestClient, fake_prices: FakePrices, fake_rates: FakeRates
    ) -> None:
        alice.patch(f"{API}/settings", json={"currency_code": "EUR"})
        fake_prices.add("AAPL", "200", "USD", d(10))
        fake_rates.rates[("USD", "EUR")] = Decimal("0.9")
        apple = create_security(alice, name="Apple", currency="USD", symbol="AAPL")
        create_security(alice, name="Gone", symbol="GONE")
        update = alice.post(
            f"{API}/investments/refresh-prices",
            json={"history_start": "2025-01-02"},
        ).json()
        assert len(update["errors"]) == 1
        assert "GONE" in update["errors"][0]
        assert {(p["security_id"], p["date"]) for p in update["prices"]} == {
            (apple["id"], "2025-01-02"),
            (apple["id"], "2025-01-10"),
        }
        assert {r["currency"] for r in update["exchange_rates"]} == {"USD"}

        only_apple = alice.post(
            f"{API}/investments/refresh-prices", json={"security_ids": [apple["id"]]}
        ).json()
        assert only_apple["errors"] == []

    def test_refresh_exchange_rates(
        self, alice: TestClient, fake_rates: FakeRates
    ) -> None:
        alice.patch(f"{API}/settings", json={"currency_code": "EUR"})
        fake_rates.rates[("CHF", "EUR")] = Decimal("1.05")
        update = alice.post(
            f"{API}/investments/refresh-exchange-rates", json={"currencies": ["CHF"]}
        ).json()
        assert [(r["currency"], r["rate"]) for r in update["exchange_rates"]] == [
            ("CHF", "1.05")
        ]
        assert (
            alice.post(f"{API}/investments/refresh-exchange-rates").status_code == 200
        )
