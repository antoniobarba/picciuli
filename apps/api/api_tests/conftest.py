from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_tests.helpers import (
    AUDIENCE,
    ISSUER,
    FakeClock,
    FakePrices,
    FakeRates,
    StaticKeys,
    Tokens,
)
from picciuli import PriceProviderError
from picciuli.prices import PriceProvider
from picciuli.rates import ExchangeRateProvider
from picciuli_api import Settings, create_app
from picciuli_api.auth import TokenVerifier
from picciuli_api.providers import SharedProviders


@pytest.fixture(scope="session")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def tokens(private_key: rsa.RSAPrivateKey) -> Tokens:
    return Tokens(private_key)


@pytest.fixture
def keys(private_key: rsa.RSAPrivateKey) -> StaticKeys:
    return StaticKeys(private_key)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, oidc_issuer=ISSUER, oidc_audience=AUDIENCE)


@pytest.fixture
def fake_prices() -> FakePrices:
    return FakePrices()


@pytest.fixture
def fake_rates() -> FakeRates:
    return FakeRates()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def providers(
    fake_prices: FakePrices, fake_rates: FakeRates, clock: FakeClock
) -> SharedProviders:
    def prices(provider_id: str) -> PriceProvider:
        if provider_id != fake_prices.id:
            raise PriceProviderError(f"unknown price provider {provider_id!r}")
        return fake_prices

    def rates(provider_id: str) -> ExchangeRateProvider:
        return fake_rates

    return SharedProviders(
        ttl=900, clock=clock, price_factory=prices, rate_factory=rates
    )


@pytest.fixture
def app(settings: Settings, keys: StaticKeys, providers: SharedProviders) -> FastAPI:
    verifier = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, keys=keys)
    return create_app(settings, verifier=verifier, providers=providers)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Anonymous client; also runs the application lifespan."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def alice(client: TestClient, app: FastAPI, tokens: Tokens) -> TestClient:
    return TestClient(app, headers=tokens.headers("alice"))


@pytest.fixture
def bob(client: TestClient, app: FastAPI, tokens: Tokens) -> TestClient:
    return TestClient(app, headers=tokens.headers("bob"))
