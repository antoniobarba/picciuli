"""Test doubles and helpers shared by the API tests."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from picciuli import PriceProviderError
from picciuli.prices import PricePoint, PriceProvider, Quote, SecurityInfo
from picciuli.rates import ExchangeRateProvider, RatePoint, RateQuote

ISSUER = "https://auth.test"
AUDIENCE = "picciuli-test"
KID = "test-key"
API = "/api/v1"


def d(day: int, month: int = 1, year: int = 2025) -> dt.date:
    return dt.date(year, month, day)


class StaticKeys:
    """A JWKS with one key, served without any network access."""

    def __init__(self, private_key: rsa.RSAPrivateKey) -> None:
        public = jwt.algorithms.RSAAlgorithm.to_jwk(
            private_key.public_key(), as_dict=True
        )
        public.update(kid=KID, alg="RS256", use="sig")
        self.key = jwt.PyJWK(public)

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        if jwt.get_unverified_header(token).get("kid") != KID:
            raise jwt.PyJWKClientError("unknown signing key")
        return self.key


class Tokens:
    """Issue access tokens like the identity provider would."""

    def __init__(self, private_key: rsa.RSAPrivateKey) -> None:
        self.private_key = private_key

    def __call__(
        self,
        subject: str | None = "alice",
        *,
        issuer: str = ISSUER,
        audience: str | list[str] = AUDIENCE,
        expires_in: int = 300,
        key: Any = None,
        kid: str = KID,
        algorithm: str = "RS256",
    ) -> str:
        now = dt.datetime.now(dt.timezone.utc)
        claims: dict[str, Any] = {
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + dt.timedelta(seconds=expires_in),
        }
        if subject is not None:
            claims["sub"] = subject
        return jwt.encode(
            claims,
            key if key is not None else self.private_key,
            algorithm=algorithm,
            headers={"kid": kid},
        )

    def headers(self, subject: str = "alice") -> dict[str, str]:
        return {"Authorization": f"Bearer {self(subject)}"}


class FakePrices(PriceProvider):
    id = "yahoo"
    name = "Fake Yahoo"

    def __init__(self) -> None:
        self.quotes: dict[str, Quote] = {}
        self.calls: list[str] = []

    def add(self, symbol: str, price: str, currency: str, day: dt.date) -> None:
        moment = dt.datetime.combine(day, dt.time(17), dt.timezone.utc)
        self.quotes[symbol] = Quote(symbol, Decimal(price), currency, moment)

    def latest(self, symbol: str) -> Quote:
        self.calls.append(symbol)
        if symbol not in self.quotes:
            raise PriceProviderError(f"no quote for {symbol}")
        return self.quotes[symbol]

    def history(self, symbol: str, start: dt.date, end: dt.date) -> list[PricePoint]:
        return [PricePoint(start, self.quotes[symbol].price)]

    def search(self, query: str) -> list[SecurityInfo]:
        if query == "fail":
            raise PriceProviderError("search is down")
        return [
            SecurityInfo("VWCE.DE", "Vanguard FTSE All-World", "XETRA", "ETF", "EUR")
        ]


class FakeRates(ExchangeRateProvider):
    id = "yahoo"
    name = "Fake Yahoo rates"

    def __init__(self) -> None:
        self.rates: dict[tuple[str, str], Decimal] = {}
        self.calls: list[tuple[str, str]] = []

    def latest(self, currency: str, base: str) -> RateQuote:
        self.calls.append((currency, base))
        if (currency, base) not in self.rates:
            raise PriceProviderError(f"no rate for {currency}{base}")
        moment = dt.datetime.combine(d(10), dt.time(17), dt.timezone.utc)
        return RateQuote(currency, base, self.rates[(currency, base)], moment)

    def history(
        self, currency: str, base: str, start: dt.date, end: dt.date
    ) -> list[RatePoint]:
        return [RatePoint(start, self.rates[(currency, base)])]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def create_account(
    api: TestClient, name: str = "Checking", type: str = "checking", **extra: Any
) -> dict[str, Any]:
    response = api.post(f"{API}/accounts", json={"name": name, "type": type, **extra})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def create_category(
    api: TestClient, name: str = "Food", **extra: Any
) -> dict[str, Any]:
    response = api.post(f"{API}/categories", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result
