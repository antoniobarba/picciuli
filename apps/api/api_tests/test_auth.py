from __future__ import annotations

import logging
import re

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api_tests.helpers import API, AUDIENCE, ISSUER, StaticKeys, Tokens
from picciuli_api import Settings
from picciuli_api.auth import (
    AuthenticationError,
    AuthUnavailableError,
    TokenVerifier,
    User,
)


@pytest.fixture
def verifier(keys: StaticKeys) -> TokenVerifier:
    return TokenVerifier(issuer=ISSUER, audience=AUDIENCE, keys=keys, leeway=0)


class TestVerifier:
    def test_valid_token(self, verifier: TokenVerifier, tokens: Tokens) -> None:
        assert verifier.verify(tokens("alice")) == User(ISSUER, "alice")

    def test_audience_list(self, verifier: TokenVerifier, tokens: Tokens) -> None:
        token = tokens("alice", audience=["other", AUDIENCE])
        assert verifier.verify(token).subject == "alice"

    @pytest.mark.parametrize(
        ("options", "reason"),
        [
            ({"expires_in": -60}, "expired"),
            ({"audience": "someone-else"}, "(?i)audience"),
            ({"issuer": "https://evil.test"}, "issuer"),
            ({"subject": None}, "sub"),
            ({"kid": "rotated-away"}, "unknown signing key"),
            ({"issued_in": None}, "iat"),
            ({"issued_in": 3600, "expires_in": 7200}, "iat"),
            ({"issued_in": -60, "expires_in": 24 * 3600}, "lifetime"),
            ({"expires_in": 10 * 365 * 24 * 3600}, "lifetime"),
            ({"subject": ""}, "empty subject"),
        ],
    )
    def test_rejected_claims(
        self,
        verifier: TokenVerifier,
        tokens: Tokens,
        options: dict[str, object],
        reason: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO, logger="picciuli_api.auth")
        with pytest.raises(AuthenticationError) as error:
            verifier.verify(tokens(**options))  # type: ignore[arg-type]
        assert str(error.value) == "invalid access token"
        assert re.search(reason, caplog.text)

    def test_lifetime_is_configurable(self, keys: StaticKeys, tokens: Tokens) -> None:
        verifier = TokenVerifier(
            issuer=ISSUER, audience=AUDIENCE, keys=keys, max_lifetime=600
        )
        assert verifier.verify(tokens(expires_in=600)).subject == "alice"
        with pytest.raises(AuthenticationError):
            verifier.verify(tokens(expires_in=601))

    def test_forged_signature(self, verifier: TokenVerifier, tokens: Tokens) -> None:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(AuthenticationError, match=r"^invalid access token$"):
            verifier.verify(tokens(key=other))

    def test_symmetric_algorithms_are_refused(
        self, verifier: TokenVerifier, tokens: Tokens
    ) -> None:
        token = tokens(key="a-shared-secret-of-at-least-32-bytes!", algorithm="HS256")
        with pytest.raises(AuthenticationError):
            verifier.verify(token)

    def test_garbage(self, verifier: TokenVerifier) -> None:
        with pytest.raises(AuthenticationError):
            verifier.verify("not-a-jwt")

    def test_unreachable_keys(self, tokens: Tokens) -> None:
        class Offline:
            def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
                raise jwt.PyJWKClientConnectionError("connection refused")

        verifier = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, keys=Offline())
        with pytest.raises(AuthUnavailableError):
            verifier.verify(tokens())

    def test_from_jwks_url(self) -> None:
        verifier = TokenVerifier.from_jwks_url(
            "https://auth.test/keys", issuer=ISSUER, audience=AUDIENCE
        )
        assert verifier.issuer == ISSUER
        assert verifier.audience == AUDIENCE


class TestUser:
    def test_id_is_an_opaque_stable_digest(self) -> None:
        user = User(ISSUER, "alice@example.com")
        assert user.id == User(ISSUER, "alice@example.com").id
        assert len(user.id) == 64
        assert "alice" not in user.id

    def test_id_depends_on_issuer_and_subject(self) -> None:
        ids = {
            User(ISSUER, "alice").id,
            User(ISSUER, "bob").id,
            User("https://other.test", "alice").id,
        }
        assert len(ids) == 3


class TestEndpointAuthentication:
    def test_missing_token(self, client: TestClient) -> None:
        response = client.get(f"{API}/accounts")
        assert response.status_code == 401
        assert response.json() == {
            "error": "unauthorized",
            "detail": "missing bearer token",
        }
        assert response.headers["WWW-Authenticate"].startswith("Bearer")

    def test_wrong_scheme(self, client: TestClient) -> None:
        response = client.get(f"{API}/me", headers={"Authorization": "Basic YTpi"})
        assert response.status_code == 401

    def test_invalid_token(self, client: TestClient, tokens: Tokens) -> None:
        token = tokens(expires_in=-3600)
        response = client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json() == {
            "error": "unauthorized",
            "detail": "invalid access token",
        }

    @pytest.mark.parametrize("token", ["garbage", "a.b.c"])
    def test_garbage_token_gets_generic_body(
        self, client: TestClient, token: str
    ) -> None:
        response = client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json() == {
            "error": "unauthorized",
            "detail": "invalid access token",
        }

    def test_unauthenticated_requests_create_no_data(
        self, client: TestClient, settings: Settings
    ) -> None:
        client.get(f"{API}/accounts")
        users_dir = settings.users_dir
        assert not users_dir.exists() or not any(users_dir.iterdir())

    def test_health_needs_no_token(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
