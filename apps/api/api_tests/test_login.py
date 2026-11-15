from __future__ import annotations

import json
from collections.abc import Iterator
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from picciuli_api import Settings, create_app
from picciuli_api.login import Flow, Login, UpstreamError, Zitadel

ORIGIN = "https://app.test"


class Identity:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.policy: dict[str, Any] = {
            "allowUsernamePassword": True,
            "allowLocalAuthentication": True,
            "allowRegister": True,
            "secondFactors": ["SECOND_FACTOR_TYPE_OTP"],
        }
        self.user: dict[str, Any] = {
            "userId": "user",
            "state": "USER_STATE_ACTIVE",
            "details": {"resourceOwner": "org"},
            "human": {"email": {"isVerified": True}},
        }
        self.factors: dict[str, Any] = {
            "user": {"id": "user", "verifiedAt": "now"},
            "password": {"verifiedAt": "now"},
        }
        self.methods: list[str] = []
        self.client_id = "web"
        self.redirect_uri = ORIGIN + "/callback"
        self.callback = self.redirect_uri + "?code=one-time-code&state=state"
        self.fail: str = ""
        self.found = True

    def call(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, path, body))
        if self.fail and self.fail in path:
            raise UpstreamError(400)
        if path.startswith("/v2/settings/login"):
            assert "ctx.orgId=org" in path
            return {"settings": self.policy}
        if path.startswith("/v2/settings/password"):
            return {"settings": {"minLength": "8", "requiresNumber": True}}
        if path.startswith("/v2/oidc/auth_requests/"):
            if method == "GET":
                return {
                    "authRequest": {
                        "clientId": self.client_id,
                        "redirectUri": self.redirect_uri,
                    }
                }
            assert body is not None
            assert body["session"]["sessionToken"] == "session-token"
            return {"callbackUrl": self.callback}
        if path == "/v2/sessions" and method == "POST":
            assert body is not None
            if body["checks"]["password"]["password"] != "correct":
                raise UpstreamError(400)
            return {"sessionId": "session", "sessionToken": "session-token"}
        if path.startswith("/v2/sessions/session"):
            if method == "GET":
                return {"session": {"factors": self.factors}}
            if method == "PATCH":
                assert body is not None
                self.factors.update(body["checks"])
                return {"sessionToken": "session-token"}
            return {}
        if path == "/v2/users/user":
            return {"user": self.user}
        if path == "/v2/users/user/authentication_methods":
            return {"authMethodTypes": self.methods}
        if path == "/v2/users/human":
            return {"userId": "user"}
        if path == "/v2/users/user/email/verify":
            self.user["human"]["email"]["isVerified"] = True
            return {}
        if path == "/v2/users/user/totp":
            return {"secret": "SETUP-KEY"}
        if path == "/v2/users/user/totp/verify":
            self.methods = ["AUTHENTICATION_METHOD_TYPE_TOTP"]
            return {}
        if path == "/v2/users/user/password":
            self.user["human"]["passwordChangeRequired"] = False
            return {}
        if path == "/v2/users":
            return {"result": [self.user] if self.found else []}
        if path.endswith(("/email/resend", "/password_reset")):
            return {}
        raise AssertionError((method, path, body))


@pytest.fixture
def identity() -> Identity:
    return Identity()


@pytest.fixture
def login_settings(tmp_path: Path) -> Settings:
    return Settings(
        oidc_issuer="https://identity.test",
        oidc_audience="audience",
        data_dir=tmp_path,
        login_origin=ORIGIN,
        login_client_id="web",
        login_org_id="org",
        login_token_file=tmp_path / "pat",
        login_cookie_secret=SecretStr("a" * 48),
    )


@pytest.fixture
def browser(
    login_settings: Settings, identity: Identity, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(Zitadel, "call", lambda self, *args: identity.call(*args))
    with TestClient(create_app(login_settings), base_url=ORIGIN) as client:
        client.headers["origin"] = ORIGIN
        yield client


def start(browser: TestClient) -> None:
    response = browser.post("/api/auth/start", json={"auth_request": "V2_request"})
    assert response.status_code == 200, response.text


def sign_in(browser: TestClient) -> Any:
    return browser.post(
        "/api/auth/login",
        json={"username": "alice@example.test", "password": "correct"},
    )


def test_native_login_keeps_oidc_and_secrets_server_side(browser: TestClient) -> None:
    start(browser)
    response = sign_in(browser)
    assert response.json() == {
        "step": "complete",
        "callback_url": ORIGIN + "/callback?code=one-time-code&state=state",
    }
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert "session-token" not in cookie and "correct" not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert "/api/auth/login" not in browser.get("/openapi.json").json()["paths"]
    assert browser.get("/api/v1/accounts").status_code == 401
    assert browser.post("/api/auth/logout", json={}).json()["step"] == "signed-out"
    assert not browser.cookies


@pytest.mark.parametrize(
    "origin", ["https://evil.test", "https://other.app.test", "null", ""]
)
def test_csrf_rejected(browser: TestClient, identity: Identity, origin: str) -> None:
    response = browser.post(
        "/api/auth/start", json={"auth_request": "x"}, headers={"origin": origin}
    )
    assert response.status_code == 403
    assert not identity.calls


def test_json_required_and_credentials_not_echoed(browser: TestClient) -> None:
    assert browser.post("/api/auth/login", content="password=secret").status_code == 415
    response = browser.post(
        "/api/auth/login", json={"username": "alice", "password": ["secret"]}
    )
    assert response.status_code == 422
    assert "secret" not in response.text


def test_only_configured_oidc_client_and_callback(
    browser: TestClient, identity: Identity
) -> None:
    identity.client_id = "other"
    assert (
        browser.post("/api/auth/start", json={"auth_request": "x"}).status_code == 403
    )
    identity.client_id = "web"
    identity.redirect_uri = "https://evil.test/callback"
    assert (
        browser.post("/api/auth/start", json={"auth_request": "x"}).status_code == 403
    )


def test_missing_tampered_and_expired_cookie(
    browser: TestClient, login_settings: Settings
) -> None:
    assert sign_in(browser).status_code == 401
    browser.cookies.set("__Host-picciuli-flow", "tampered")
    assert sign_in(browser).status_code == 401
    sealed = (
        Login(login_settings)
        .cipher.encrypt_at_time(
            Flow(auth_request="request").model_dump_json().encode(), 1
        )
        .decode()
    )
    browser.cookies.set("__Host-picciuli-flow", sealed)
    assert sign_in(browser).status_code == 401


def test_wrong_password_and_wrong_organization(
    browser: TestClient, identity: Identity
) -> None:
    start(browser)
    response = browser.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong"}
    )
    assert response.status_code == 400
    identity.user["details"]["resourceOwner"] = "other"
    assert sign_in(browser).status_code == 400
    assert not any(
        method == "POST" and "/auth_requests/" in path
        for method, path, _ in identity.calls
    )


def test_unverified_email_cannot_login(browser: TestClient, identity: Identity) -> None:
    start(browser)
    identity.user["human"]["email"]["isVerified"] = False
    assert sign_in(browser).json()["step"] == "verify-email"
    assert browser.post("/api/auth/resend-email", json={}).status_code == 200
    response = browser.post("/api/auth/verify", json={"code": "email-code"})
    assert response.json()["step"] == "complete"


def test_registration_verification_and_disabled_registration(
    browser: TestClient, identity: Identity
) -> None:
    start(browser)
    body = {
        "username": "new@example.test",
        "password": "correct",
        "given_name": "New",
        "family_name": "User",
    }
    identity.policy["allowRegister"] = False
    assert browser.post("/api/auth/register", json=body).status_code == 403
    identity.policy["allowRegister"] = True
    assert browser.post("/api/auth/register", json=body).json()["step"] == "registered"
    create = next(body for _, path, body in identity.calls if path == "/v2/users/human")
    assert create is not None
    assert create["organization"] == {"orgId": "org"}
    assert "isVerified" not in create["email"]
    assert create["email"]["sendCode"]["urlTemplate"].startswith(
        ORIGIN + "/verify-email?"
    )
    assert (
        browser.post("/api/auth/verify", json={"code": "code"}).json()["step"]
        == "verified"
    )
    assert "__Host-picciuli-session" not in browser.cookies
    assert (
        browser.post(
            "/api/auth/verify-email", json={"user_id": "user", "code": "code"}
        ).json()["step"]
        == "verified"
    )


def test_enrolled_totp_is_required_even_when_mfa_is_optional(
    browser: TestClient, identity: Identity
) -> None:
    start(browser)
    identity.methods = ["AUTHENTICATION_METHOD_TYPE_TOTP"]
    assert sign_in(browser).json()["step"] == "totp"
    identity.fail = "/v2/sessions/session"
    assert browser.post("/api/auth/verify", json={"code": "wrong"}).status_code == 400
    identity.fail = ""
    assert (
        browser.post("/api/auth/verify", json={"code": "123456"}).json()["step"]
        == "complete"
    )


def test_required_mfa_enrollment(browser: TestClient, identity: Identity) -> None:
    start(browser)
    identity.policy["forceMfa"] = True
    assert sign_in(browser).json()["step"] == "setup-totp"
    assert browser.post("/api/auth/setup-totp", json={}).json()["secret"] == "SETUP-KEY"
    assert (
        browser.post("/api/auth/confirm-totp", json={"code": "123456"}).json()["step"]
        == "totp"
    )
    assert (
        browser.post("/api/auth/verify", json={"code": "654321"}).json()["step"]
        == "complete"
    )


def test_policy_change_cannot_accept_a_disabled_factor(
    browser: TestClient, identity: Identity
) -> None:
    start(browser)
    identity.methods = ["AUTHENTICATION_METHOD_TYPE_TOTP"]
    assert sign_in(browser).json()["step"] == "totp"
    identity.policy["secondFactors"] = ["SECOND_FACTOR_TYPE_U2F"]
    response = browser.post("/api/auth/verify", json={"code": "123456"})
    assert response.status_code == 403
    assert "__Host-picciuli-session" not in browser.cookies


@pytest.mark.parametrize(
    "method", ["AUTHENTICATION_METHOD_TYPE_U2F", "AUTHENTICATION_METHOD_TYPE_OTP_SMS"]
)
def test_unsupported_mfa_never_downgrades(
    browser: TestClient, identity: Identity, method: str
) -> None:
    start(browser)
    identity.methods = [method]
    assert sign_in(browser).status_code == 403


def test_password_change_then_email_mfa_checks(
    browser: TestClient, identity: Identity
) -> None:
    start(browser)
    identity.user["human"]["passwordChangeRequired"] = True
    identity.user["human"]["email"]["isVerified"] = False
    assert sign_in(browser).json()["step"] == "change-password"
    response = browser.post(
        "/api/auth/change-password",
        json={"current_password": "correct", "password": "new"},
    )
    assert response.json()["step"] == "verify-email"
    payload = next(
        body for _, path, body in identity.calls if path.endswith("/password")
    )
    assert payload == {
        "newPassword": {"password": "new", "changeRequired": False},
        "currentPassword": "correct",
    }


def test_recovery_non_enumerating_and_requires_code(
    browser: TestClient, identity: Identity
) -> None:
    first = browser.post(
        "/api/auth/reset-request", json={"username": "alice@example.test"}
    )
    identity.found = False
    second = browser.post(
        "/api/auth/reset-request", json={"username": "absent@example.test"}
    )
    assert first.json() == second.json() == {"step": "reset-sent"}
    payload = next(
        body for _, path, body in identity.calls if path.endswith("/password_reset")
    )
    assert payload is not None and payload["sendLink"]["urlTemplate"].startswith(
        ORIGIN + "/reset-password?"
    )
    assert (
        browser.post(
            "/api/auth/reset-password",
            json={"user_id": "user", "password": "new", "code": ""},
        ).status_code
        == 422
    )
    assert (
        browser.post(
            "/api/auth/reset-password",
            json={"user_id": "user", "password": "new", "code": "code"},
        ).json()["step"]
        == "password-reset"
    )
    assert "__Host-picciuli-session" not in browser.cookies
    identity.policy["hidePasswordReset"] = True
    assert (
        browser.post("/api/auth/reset-request", json={"username": "alice"}).status_code
        == 403
    )


def test_stage_cannot_be_skipped(browser: TestClient) -> None:
    start(browser)
    for action, body in [
        ("verify", {"code": "123456"}),
        ("setup-totp", {}),
        ("confirm-totp", {"code": "123456"}),
        ("resend-email", {}),
        ("change-password", {"current_password": "x", "password": "y"}),
    ]:
        assert browser.post("/api/auth/" + action, json=body).status_code == 409


def test_provider_policy_and_factors_enforced(
    browser: TestClient, identity: Identity
) -> None:
    start(browser)
    identity.policy["allowUsernamePassword"] = False
    assert sign_in(browser).status_code == 403
    identity.policy["allowUsernamePassword"] = True
    del identity.factors["password"]
    assert sign_in(browser).status_code == 403


def test_callback_redirect_is_checked(browser: TestClient, identity: Identity) -> None:
    start(browser)
    identity.callback = "https://evil.test/callback"
    assert sign_in(browser).status_code == 502


def test_request_rate_is_bounded(browser: TestClient) -> None:
    for _ in range(30):
        assert browser.post("/api/auth/logout", json={}).status_code == 200
    response = browser.post("/api/auth/logout", json={})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


@pytest.mark.parametrize(
    "failure", [URLError("secret"), HTTPError("url", 503, "secret", Message(), None)]
)
def test_transport_failures_hide_secrets(
    login_settings: Settings, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    assert login_settings.login_token_file is not None
    login_settings.login_token_file.write_text("private-pat")

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr("picciuli_api.login.urlopen", unavailable)
    with pytest.raises(HTTPException) as error:
        Zitadel(login_settings).call("POST", "/v2/sessions", {"password": "secret"})
    assert error.value.status_code == 503
    assert "secret" not in str(error.value)


def test_transport_serializes_credentials_without_logging(
    login_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from io import BytesIO

    assert login_settings.login_token_file is not None
    login_settings.login_token_file.write_text("private-pat\n")

    def upstream(request: Any, timeout: int) -> BytesIO:
        assert timeout == 15
        assert request.headers["Authorization"] == "Bearer private-pat"
        assert json.loads(request.data) == {"checks": {}}
        return BytesIO(b'{"sessionId":"session"}')

    monkeypatch.setattr("picciuli_api.login.urlopen", upstream)
    assert Zitadel(login_settings).call("POST", "/v2/sessions", {"checks": {}}) == {
        "sessionId": "session"
    }


@pytest.mark.parametrize("origin", ["http://app.test", "https://app.test/path"])
def test_native_configuration_rejects_unsafe_origins_without_leaking_secrets(
    login_settings: Settings, origin: str
) -> None:
    values = login_settings.model_dump()
    values["login_origin"] = origin
    values["login_cookie_secret"] = "private-cookie-key" * 3
    with pytest.raises(ValidationError) as error:
        Settings.model_validate(values)
    assert "private-cookie-key" not in str(error.value)
