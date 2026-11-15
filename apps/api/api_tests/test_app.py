from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_tests.helpers import API, AUDIENCE, ISSUER, StaticKeys, Tokens
from picciuli import PicciuliError
from picciuli_api import Settings, create_app
from picciuli_api.auth import TokenVerifier, User


class TestSettings:
    def test_from_environment(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("PICCIULI_OIDC_ISSUER", "https://auth.example.com/")
        monkeypatch.setenv("PICCIULI_OIDC_AUDIENCE", "123")
        monkeypatch.setenv("PICCIULI_DATA_DIR", str(tmp_path))
        monkeypatch.setenv(
            "PICCIULI_CORS_ORIGINS", "https://app.example.com, http://localhost:5173,"
        )
        monkeypatch.setenv("PICCIULI_PRICE_CACHE_SECONDS", "60")
        settings = Settings()  # type: ignore[call-arg]
        assert settings.cors_origins == [
            "https://app.example.com",
            "http://localhost:5173",
        ]
        assert settings.jwks_url == "https://auth.example.com/oauth/v2/keys"
        assert settings.users_dir == tmp_path / "users"
        assert settings.price_cache_seconds == 60

    def test_explicit_jwks_url(self) -> None:
        settings = Settings(
            oidc_issuer=ISSUER, oidc_audience=AUDIENCE, oidc_jwks_url="https://k/"
        )
        assert settings.jwks_url == "https://k/"

    def test_issuer_is_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PICCIULI_OIDC_ISSUER", raising=False)
        with pytest.raises(ValueError, match="oidc_issuer"):
            Settings(oidc_audience=AUDIENCE)  # type: ignore[call-arg]


class TestDocs:
    def test_swagger_and_redoc(self, client: TestClient) -> None:
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        schema = client.get("/openapi.json").json()
        assert "bearer" in schema["components"]["securitySchemes"]
        assert "oidc" not in schema["components"]["securitySchemes"]

    def test_docs_can_be_disabled(self, settings: Settings, keys: StaticKeys) -> None:
        settings.docs_enabled = False
        app = create_app(settings, verifier=self._verifier(keys))
        client = TestClient(app)
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404

    def test_swagger_login_with_oidc(
        self, settings: Settings, keys: StaticKeys
    ) -> None:
        settings.oidc_swagger_client_id = "swagger-client"
        app = create_app(settings, verifier=self._verifier(keys))
        client = TestClient(app)
        html = client.get("/docs").text
        assert "swagger-client" in html
        assert "usePkceWithAuthorizationCodeGrant" in html
        schema = client.get("/openapi.json").json()
        assert schema["components"]["securitySchemes"]["oidc"] == {
            "type": "openIdConnect",
            "openIdConnectUrl": f"{ISSUER}/.well-known/openid-configuration",
        }
        operation = schema["paths"][f"{API}/accounts"]["get"]
        assert operation["security"] == [{"bearer": []}, {"oidc": []}]
        assert app.openapi() is app.openapi()

    def test_default_verifier_downloads_keys_from_the_issuer(
        self, settings: Settings
    ) -> None:
        app = create_app(settings)
        verifier = app.state.context.verifier
        assert verifier.issuer == ISSUER
        assert verifier.audience == AUDIENCE

    @staticmethod
    def _verifier(keys: StaticKeys) -> TokenVerifier:
        return TokenVerifier(issuer=ISSUER, audience=AUDIENCE, keys=keys)


class TestCors:
    def test_allowed_origin(
        self, settings: Settings, keys: StaticKeys, tokens: Tokens
    ) -> None:
        settings.cors_origins = ["https://app.example.com"]
        verifier = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, keys=keys)
        with TestClient(create_app(settings, verifier=verifier)) as client:
            response = client.options(
                f"{API}/accounts",
                headers={
                    "Origin": "https://app.example.com",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert response.status_code == 200
            allowed = "https://app.example.com"
            assert response.headers["access-control-allow-origin"] == allowed
            response = client.get(
                f"{API}/accounts",
                headers={"Origin": "https://evil.example.com", **tokens.headers()},
            )
            assert "access-control-allow-origin" not in response.headers

    def test_no_cors_by_default(self, client: TestClient) -> None:
        response = client.options(
            f"{API}/accounts",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in response.headers


class TestErrors:
    def test_unknown_route(self, alice: TestClient) -> None:
        response = alice.get(f"{API}/nothing-here")
        assert response.status_code == 404
        assert response.json() == {"error": "not_found", "detail": "Not Found"}

    def test_method_not_allowed(self, alice: TestClient) -> None:
        response = alice.put(f"{API}/accounts")
        assert response.status_code == 405
        assert response.json()["error"] == "method_not_allowed"

    def test_invalid_request(self, alice: TestClient) -> None:
        response = alice.post(f"{API}/accounts", json={"name": "X", "type": "boat"})
        assert response.status_code == 422
        body = response.json()
        assert body["error"] == "invalid_request"
        assert body["errors"][0]["loc"] == ["body", "type"]

    def test_unknown_fields_are_rejected(self, alice: TestClient) -> None:
        response = alice.post(
            f"{API}/accounts", json={"name": "X", "type": "cash", "colour": "red"}
        )
        assert response.status_code == 422

    def test_library_validation_error(self, alice: TestClient) -> None:
        response = alice.post(f"{API}/accounts", json={"name": " ", "type": "cash"})
        assert response.status_code == 422
        assert response.json()["error"] == "validation_error"

    def test_not_found(self, alice: TestClient) -> None:
        response = alice.get(f"{API}/accounts/999")
        assert response.status_code == 404
        assert response.json()["error"] == "not_found"
        assert "999" in response.json()["detail"]

    def test_conflict(self, alice: TestClient) -> None:
        for expected in (201, 409):
            response = alice.post(
                f"{API}/accounts", json={"name": "Twin", "type": "cash"}
            )
            assert response.status_code == expected
        assert response.json()["error"] == "conflict"

    def test_foreign_sqlite_database(
        self, alice: TestClient, settings: Settings
    ) -> None:
        settings.users_dir.mkdir(parents=True)
        path = settings.users_dir / f"{User(ISSUER, 'alice').id}.db"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE something_else (x INTEGER)")
        connection.commit()
        connection.close()
        response = alice.get(f"{API}/accounts")
        assert response.status_code == 500
        assert response.json()["error"] == "schema_version_error"

    def test_unexpected_errors_hide_details(
        self, app: FastAPI, settings: Settings, tokens: Tokens
    ) -> None:
        settings.users_dir.mkdir(parents=True)
        path = settings.users_dir / f"{User(ISSUER, 'alice').id}.db"
        path.write_bytes(b"not a database, " * 1000)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(f"{API}/accounts", headers=tokens.headers())
        assert response.status_code == 500
        assert response.json() == {
            "error": "internal_error",
            "detail": "internal error",
        }

    def test_unexpected_library_error(self, app: FastAPI) -> None:
        @app.get("/boom")
        def boom() -> None:
            raise PicciuliError("secret internals")

        response = TestClient(app).get("/boom")
        assert response.status_code == 500
        assert response.json() == {
            "error": "internal_error",
            "detail": "internal error",
        }
